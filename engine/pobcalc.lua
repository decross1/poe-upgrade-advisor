local buildPath, itemPath, preset, presetConfigJson = arg[1], arg[2], arg[3], arg[4]
-- Thin, unmodified-PoB adapter for the TASK-101 spike. Upstream startup logs
-- use stdout, which is the CLI's JSON channel, so silence them during boot.
print = function() end
dofile("HeadlessWrapper.lua")
local json = require("dkjson")
local dataRoot = os.getenv("POBCALC_DATA_ROOT")
if not dataRoot or dataRoot == "" then
	error("POBCALC_DATA_ROOT is required")
end

local fileSearch = { }
fileSearch.__index = fileSearch
function fileSearch:GetFileName()
	return self.path:match("[^/\\]+$") or self.path
end
function fileSearch:GetFileModifiedTime()
	return 1
end
function fileSearch:NextFile()
	return false
end
function NewFileSearch(path)
	local file = io.open(path, "rb")
	if not file then
		return nil
	end
	file:close()
	return setmetatable({ path = path }, fileSearch)
end
function GetScriptPath()
	return dataRoot
end

local presetDocument, _, presetDecodeError = json.decode(presetConfigJson, 1, nil)
if presetDecodeError or type(presetDocument) ~= "table"
		or type(presetDocument.presets) ~= "table" then
	error("invalid compiled preset configuration: " .. tostring(presetDecodeError))
end

local function presetConfig(name)
	local config = presetDocument.presets[name]
	if type(config) ~= "table" then
		error("unsupported preset: " .. tostring(name))
	end
	return config
end

local function applyConfig(config)
	if type(config) ~= "table" then
		error("configuration must be an object")
	end
	local changed = false
	local input = build.configTab.configSets[build.configTab.activeConfigSetId].input
	for key, value in pairs(config) do
		if key == "flasks_active" then
			for _, slot in ipairs(build.itemsTab.orderedSlots) do
				if slot.slotName:match("^Flask %d+$") then
					if slot.active ~= value then
						changed = true
					end
					slot.active = value
					build.itemsTab.activeItemSet[slot.slotName].active = value
				end
			end
		else
			if input[key] ~= value
					and not (input[key] == nil and value == false) then
				changed = true
			end
			input[key] = value
		end
	end
	build.configTab.input = input
	return changed
end

local function readAll(path)
	local file, err = io.open(path, "rb")
	if not file then
		error("cannot open " .. path .. ": " .. tostring(err))
	end
	local value = file:read("*a")
	file:close()
	return value
end

local function jsonString(value)
	return '"' .. tostring(value):gsub('[%z\1-\31\\"]', function(char)
		local escapes = { ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b',
			['\f'] = '\\f', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
		return escapes[char] or string.format("\\u%04x", char:byte())
	end) .. '"'
end

local function jsonNumber(value)
	if value == nil or value ~= value or value == math.huge or value == -math.huge then
		return "null"
	end
	if value == 0 then
		return "0"
	end
	return string.format("%.17g", value)
end

local function metrics(output)
	return {
		total_dps = output.FullDPS or output.CombinedDPS or output.TotalDPS or 0,
		ehp = output.TotalEHP or 0,
	}
end

local function metricsJson(value)
	return '{"total_dps":' .. jsonNumber(value.total_dps)
		.. ',"ehp":' .. jsonNumber(value.ehp) .. '}'
end

local function round(value, digits)
	local scale = 10 ^ digits
	if value < 0 then
		return math.ceil(value * scale - 0.5) / scale
	end
	return math.floor(value * scale + 0.5) / scale
end

local function jsonDecimal(value, digits)
	local encoded = string.format("%." .. tostring(digits) .. "f", value)
	encoded = encoded:gsub("(%..-)0+$", "%1"):gsub("%.$", "")
	if encoded == "-0" then
		return "0"
	end
	return encoded
end

local function sortedKeys(value)
	local keys = { }
	for key in pairs(value) do
		table.insert(keys, key)
	end
	table.sort(keys)
	return keys
end

local function playerStatsJson(value)
	local parts = { }
	for _, key in ipairs(sortedKeys(value)) do
		local stat = value[key]
		local encoded
		if stat == math.huge then
			encoded = jsonString("Infinity")
		elseif stat == -math.huge then
			encoded = jsonString("-Infinity")
		else
			encoded = jsonNumber(stat)
		end
		table.insert(parts, jsonString(key) .. ":" .. encoded)
	end
	return "{" .. table.concat(parts, ",") .. "}"
end

local function identityJson(value)
	return '{"base_class":' .. jsonString(value.base_class)
		.. ',"ascendancy":' .. jsonString(value.ascendancy)
		.. ',"level":' .. jsonNumber(value.level) .. '}'
end

local cachedBuildPath
local cachedBuildXml
local cachedConfigKey
local cachedCalculate
local cachedBaselineOutput
local cachedStatsBuildPath
local cachedStatsBuildXml
local cachedStatsJson

local function loadBuild(buildXml, requestBuildPath)
	loadBuildFromXML(buildXml, requestBuildPath)
	if launch.promptMsg then
		error("Path of Building failed to load the build: " .. launch.promptMsg)
	end
end

local function prepareCalculation(requestBuildPath, requestConfig, requestConfigKey)
	local buildXml = readAll(requestBuildPath)
	if requestBuildPath == cachedBuildPath
			and buildXml == cachedBuildXml
			and requestConfigKey == cachedConfigKey then
		return cachedCalculate, cachedBaselineOutput
	end

	loadBuild(buildXml, requestBuildPath)
	if applyConfig(requestConfig) then
		build.calcsTab:BuildOutput()
	end
	local calculate, baselineOutput = build.calcsTab:GetMiscCalculator()
	cachedBuildPath = requestBuildPath
	cachedBuildXml = buildXml
	cachedConfigKey = requestConfigKey
	cachedCalculate = calculate
	cachedBaselineOutput = baselineOutput
	return calculate, baselineOutput
end

local function calculateDiff(
		requestBuildPath,
		requestItemPath,
		requestConfig,
		requestConfigKey
	)
	local calculate, baselineOutput = prepareCalculation(
		requestBuildPath,
		requestConfig,
		requestConfigKey
	)
	local candidateItem = new("Item", readAll(requestItemPath))
	if not candidateItem.base then
		error("candidate item has an unknown or invalid base")
	end
	local slot = build.itemsTab:GetComparisonSlotNameForItem(candidateItem)
	if not slot or not build.itemsTab:IsItemValidForSlot(candidateItem, slot) then
		error("candidate item has no valid comparison slot")
	end

	local candidateOutput = calculate({ repSlotName = slot, repItem = candidateItem }, true)
	local baseline = metrics(baselineOutput)
	local candidate = metrics(candidateOutput)
	local deltas = {
		total_dps = candidate.total_dps - baseline.total_dps,
		ehp = candidate.ehp - baseline.ehp,
	}

	return '{"baseline":' .. metricsJson(baseline)
		.. ',"candidate":' .. metricsJson(candidate)
		.. ',"deltas":' .. metricsJson(deltas)
		.. ',"slot":' .. jsonString(slot)
		.. ',"breakdown_ref":' .. jsonString("pob://calcs/" .. slot)
		.. '}'
end

local function percentageDelta(baseline, candidate)
	if baseline == 0 then
		if candidate == 0 then
			return 0
		end
		return nil
	end
	return (candidate - baseline) / math.abs(baseline) * 100
end

local function restoreCalculation(
		requestBuildPath,
		requestConfig,
		requestConfigKey
	)
	local buildXml = readAll(requestBuildPath)
	loadBuild(buildXml, requestBuildPath)
	if applyConfig(requestConfig) then
		build.calcsTab:BuildOutput()
	end
	local calculate, baselineOutput = build.calcsTab:GetMiscCalculator()
	cachedBuildPath = requestBuildPath
	cachedBuildXml = buildXml
	cachedConfigKey = requestConfigKey
	cachedCalculate = calculate
	cachedBaselineOutput = baselineOutput
	return calculate, baselineOutput
end

local function treeSuggestionJson(suggestion)
	local pathParts = { }
	for _, nodeId in ipairs(suggestion.path_node_ids) do
		table.insert(pathParts, jsonNumber(nodeId))
	end
	return '{"step":' .. jsonNumber(suggestion.step)
		.. ',"node_id":' .. jsonNumber(suggestion.node_id)
		.. ',"node_name":' .. jsonString(suggestion.node_name)
		.. ',"offense_delta_pct":'
		.. jsonDecimal(suggestion.offense_delta_pct, 1)
		.. ',"defense_delta_pct":'
		.. jsonDecimal(suggestion.defense_delta_pct, 1)
		.. ',"combined_score":'
		.. jsonDecimal(suggestion.combined_score, 3)
		.. ',"path_cost":' .. jsonNumber(suggestion.path_cost)
		.. ',"path_node_ids":[' .. table.concat(pathParts, ",") .. ']}'
end

local function calculateTreeSuggestions(
		requestBuildPath,
		requestConfig,
		requestConfigKey,
		points
	)
	if type(points) ~= "number"
			or points % 1 ~= 0
			or points < 1
			or points > 10 then
		error("points must be an integer from 1 to 10")
	end

	prepareCalculation(requestBuildPath, requestConfig, requestConfigKey)
	local ok, result = xpcall(function()
		local suggestions = { }
		local spent = 0
		while spent < points do
			local calculate, currentOutput = build.calcsTab:GetMiscCalculator()
			local currentMetrics = metrics(currentOutput)
			local remaining = points - spent
			local best

			for nodeId, node in pairs(build.spec.nodes) do
				if not node.alloc
						and not build.calcsTab.mainEnv.grantedPassives[nodeId]
						and not node.ascendancyName
						and node.modKey ~= ""
						and (node.type == "Normal"
							or node.type == "Notable"
							or node.type == "Keystone")
						and node.path
						and #node.path >= 1
						and #node.path <= remaining then
					local addNodes = { }
					for _, pathNode in ipairs(node.path) do
						addNodes[pathNode] = true
					end
					local candidateOutput = calculate(
						{ addNodes = addNodes },
						true
					)
					local candidateMetrics = metrics(candidateOutput)
					local offense = percentageDelta(
						currentMetrics.total_dps,
						candidateMetrics.total_dps
					)
					local defence = percentageDelta(
						currentMetrics.ehp,
						candidateMetrics.ehp
					)
					if offense ~= nil and defence ~= nil then
						offense = round(offense, 1)
						defence = round(defence, 1)
						local score = round(
							(0.8 * offense + 0.2 * defence) / #node.path,
							3
						)
						if not best
								or score > best.combined_score
								or (score == best.combined_score
									and #node.path < best.path_cost)
								or (score == best.combined_score
									and #node.path == best.path_cost
									and nodeId < best.node_id) then
							local pathNodeIds = { }
							local pathNodes = { }
							for index = #node.path, 1, -1 do
								table.insert(pathNodeIds, node.path[index].id)
							end
							for index, pathNode in ipairs(node.path) do
								pathNodes[index] = pathNode
							end
							best = {
								node = node,
								node_id = nodeId,
								node_name = node.dn or node.name or tostring(nodeId),
								offense_delta_pct = offense,
								defense_delta_pct = defence,
								combined_score = score,
								path_cost = #pathNodes,
								path_node_ids = pathNodeIds,
								path_nodes = pathNodes,
							}
						end
					end
				end
			end

			if not best then
				break
			end
			build.spec:AllocNode(best.node, best.path_nodes)
			build.calcsTab:BuildOutput()
			spent = spent + best.path_cost
			table.insert(suggestions, {
				step = #suggestions + 1,
				node_id = best.node_id,
				node_name = best.node_name,
				offense_delta_pct = best.offense_delta_pct,
				defense_delta_pct = best.defense_delta_pct,
				combined_score = best.combined_score,
				path_cost = best.path_cost,
				path_node_ids = best.path_node_ids,
			})
		end

		local parts = { }
		for index, suggestion in ipairs(suggestions) do
			parts[index] = treeSuggestionJson(suggestion)
		end
		return '{"suggestions":[' .. table.concat(parts, ",") .. ']}'
	end, debug.traceback)

	local restored, restoreError = xpcall(function()
		restoreCalculation(
			requestBuildPath,
			requestConfig,
			requestConfigKey
		)
	end, debug.traceback)
	if not restored then
		error("failed to restore active build after tree plan: " .. restoreError)
	end
	if not ok then
		error(result)
	end
	return result
end

local function loadSession(requestBuildPath, requestConfig, requestConfigKey)
	prepareCalculation(requestBuildPath, requestConfig, requestConfigKey)
	local identity = {
		base_class = build.spec.curClassName,
		ascendancy = build.spec.curAscendClassName or "None",
		level = build.characterLevel,
	}
	return '{"identity":' .. identityJson(identity) .. '}'
end

local function calculateStats(requestBuildPath)
	local buildXml = readAll(requestBuildPath)
	if requestBuildPath == cachedStatsBuildPath
			and buildXml == cachedStatsBuildXml then
		return cachedStatsJson
	end

	loadBuild(buildXml, requestBuildPath)
	local savedBuild = { elem = "Build" }
	build:Save(savedBuild)
	local stats = { }
	for _, node in ipairs(savedBuild) do
		if node.elem == "PlayerStat" then
			local name = node.attrib.stat
			local value = tonumber(node.attrib.value)
			if not name or value == nil then
				error("non-numeric PlayerStat emitted by Path of Building")
			end
			if stats[name] ~= nil and stats[name] ~= value then
				error("conflicting duplicate PlayerStat emitted by Path of Building: " .. name)
			end
			stats[name] = value
		end
	end
	local identity = {
		base_class = savedBuild.attrib.className,
		ascendancy = savedBuild.attrib.ascendClassName,
		level = tonumber(savedBuild.attrib.level),
	}
	local result = '{"identity":' .. identityJson(identity)
		.. ',"player_stats":' .. playerStatsJson(stats) .. '}'
	cachedStatsBuildPath = requestBuildPath
	cachedStatsBuildXml = buildXml
	cachedStatsJson = result
	return result
end

local function oneShot()
	local ok, result = xpcall(function()
		if buildPath == "--stats" then
			return calculateStats(itemPath)
		end
		return calculateDiff(
			buildPath,
			itemPath,
			presetConfig(preset),
			"preset:" .. preset
		)
	end, debug.traceback)

	if not ok then
		io.stderr:write("pobcalc: " .. result .. "\n")
		os.exit(70)
	end
	io.write(result, "\n")
end

local function serve()
	for line in io.lines() do
		local request, _, decodeError = json.decode(line, 1, nil)
		local id = type(request) == "table" and request.id or nil
		local idJson = "null"
		if type(id) == "string" then
			idJson = jsonString(id)
		elseif type(id) == "number" then
			idJson = jsonNumber(id)
		end
		local response
		if decodeError or type(request) ~= "table" then
			response = '{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}'
		elseif request.jsonrpc ~= "2.0"
				or (request.method ~= "diff"
					and request.method ~= "load"
					and request.method ~= "ping"
					and request.method ~= "stats"
					and request.method ~= "tree_suggestions")
				or type(request.params) ~= "table" then
			response = '{"jsonrpc":"2.0","id":' .. idJson
				.. ',"error":{"code":-32600,"message":"Invalid Request"}}'
		else
			local ok, result = xpcall(function()
				if request.method == "ping" then
					return '{"ready":true}'
				end
				if request.method == "stats" then
					return calculateStats(request.params.build)
				end
				local requestConfig = request.params.config
				local requestConfigKey = request.params.config_key
				if type(requestConfig) ~= "table" then
					requestConfig = presetConfig(request.params.preset)
					requestConfigKey = "preset:" .. request.params.preset
				elseif type(requestConfigKey) ~= "string" then
					error("config_key is required with config")
				end
				if request.method == "load" then
					return loadSession(
						request.params.build,
						requestConfig,
						requestConfigKey
					)
				end
				if request.method == "tree_suggestions" then
					return calculateTreeSuggestions(
						request.params.build,
						requestConfig,
						requestConfigKey,
						request.params.points
					)
				end
				return calculateDiff(
					request.params.build,
					request.params.item,
					requestConfig,
					requestConfigKey
				)
			end, debug.traceback)
			if ok then
				response = '{"jsonrpc":"2.0","id":' .. idJson .. ',"result":' .. result .. '}'
			else
				response = '{"jsonrpc":"2.0","id":' .. idJson
					.. ',"error":{"code":-32602,"message":'
					.. jsonString(result) .. '}}'
			end
		end
		io.write(response, "\n")
		io.flush()
	end
end

if buildPath == "--serve" then
	serve()
else
	oneShot()
end
