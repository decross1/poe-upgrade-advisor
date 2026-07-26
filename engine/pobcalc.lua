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

local function applyPreset(name)
	local config = presetDocument.presets[name]
	if type(config) ~= "table" then
		error("unsupported preset: " .. tostring(name))
	end
	local input = build.configTab.configSets[build.configTab.activeConfigSetId].input
	for key, value in pairs(config) do
		input[key] = value
	end
	build.configTab.input = input
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
local cachedPreset
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

local function prepareCalculation(requestBuildPath, requestPreset)
	local buildXml = readAll(requestBuildPath)
	if requestBuildPath == cachedBuildPath
			and buildXml == cachedBuildXml
			and requestPreset == cachedPreset then
		return cachedCalculate, cachedBaselineOutput
	end

	loadBuild(buildXml, requestBuildPath)
	applyPreset(requestPreset)
	build.calcsTab:BuildOutput()
	local calculate, baselineOutput = build.calcsTab:GetMiscCalculator()
	cachedBuildPath = requestBuildPath
	cachedBuildXml = buildXml
	cachedPreset = requestPreset
	cachedCalculate = calculate
	cachedBaselineOutput = baselineOutput
	return calculate, baselineOutput
end

local function calculateDiff(requestBuildPath, requestItemPath, requestPreset)
	local calculate, baselineOutput = prepareCalculation(
		requestBuildPath,
		requestPreset
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

local function calculateStats(requestBuildPath)
	local buildXml = readAll(requestBuildPath)
	if requestBuildPath == cachedStatsBuildPath
			and buildXml == cachedStatsBuildXml then
		return cachedStatsJson
	end

	loadBuild(buildXml, requestBuildPath)
	build.calcsTab:BuildOutput()
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
		return calculateDiff(buildPath, itemPath, preset)
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
				or (request.method ~= "diff" and request.method ~= "stats")
				or type(request.params) ~= "table" then
			response = '{"jsonrpc":"2.0","id":' .. idJson
				.. ',"error":{"code":-32600,"message":"Invalid Request"}}'
		else
			local ok, result = xpcall(function()
				if request.method == "stats" then
					return calculateStats(request.params.build)
				end
				return calculateDiff(
					request.params.build,
					request.params.item,
					request.params.preset
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
