local buildPath, itemPath, preset = arg[1], arg[2], arg[3]
-- Thin, unmodified-PoB adapter for the TASK-101 spike. Upstream startup logs
-- use stdout, which is the CLI's JSON channel, so silence them during boot.
print = function() end
dofile("HeadlessWrapper.lua")

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

local ok, result = xpcall(function()
	if preset ~= "mapping" and preset ~= "bossing" and preset ~= "balanced" then
		error("unsupported preset: " .. tostring(preset))
	end

	loadBuildFromXML(readAll(buildPath), buildPath)
	build.calcsTab:BuildOutput()

	local candidateItem = new("Item", readAll(itemPath))
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
end, debug.traceback)

if not ok then
	io.stderr:write("pobcalc: " .. result .. "\n")
	os.exit(70)
end
io.write(result, "\n")
