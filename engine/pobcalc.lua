local buildPath, itemPath, preset, presetConfigJson = arg[1], arg[2], arg[3], arg[4]
-- Thin, unmodified-PoB adapter for the TASK-101 spike. Upstream startup logs
-- use stdout, which is the CLI's JSON channel, so silence them during boot.
print = function() end
dofile("HeadlessWrapper.lua")
local json = require("dkjson")
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

local function calculateDiff(requestBuildPath, requestItemPath, requestPreset)
	loadBuildFromXML(readAll(requestBuildPath), requestBuildPath)
	applyPreset(requestPreset)
	build.calcsTab:BuildOutput()

	local candidateItem = new("Item", readAll(requestItemPath))
	if not candidateItem.base then
		error("candidate item has an unknown or invalid base")
	end
	local slot = build.itemsTab:GetComparisonSlotNameForItem(candidateItem)
	if not slot or not build.itemsTab:IsItemValidForSlot(candidateItem, slot) then
		error("candidate item has no valid comparison slot")
	end

	local calculate, baselineOutput = build.calcsTab:GetMiscCalculator()
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

local function oneShot()
	local ok, result = xpcall(function()
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
		elseif request.jsonrpc ~= "2.0" or request.method ~= "diff" or type(request.params) ~= "table" then
			response = '{"jsonrpc":"2.0","id":' .. idJson
				.. ',"error":{"code":-32600,"message":"Invalid Request"}}'
		else
			local ok, result = xpcall(function()
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
