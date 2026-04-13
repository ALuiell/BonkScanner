[ENABLE]
{$lua}
if syntaxcheck then return end

local STATE_KEY = '__megabonk_interactables_state'
local state = _G[STATE_KEY]

if state and state.timer then
  pcall(function()
    state.timer.Enabled = false
    state.timer.destroy()
  end)
end

state = {
  registered = {},
  timer = nil,
  lastSnapshot = nil,
  didInitialPrint = false,
  lastRuntimeError = nil,
}
_G[STATE_KEY] = state

local REFRESH_INTERVAL_MS = 5000

local TARGETS = {
  { label = 'Boss Curses',    slug = 'boss_curses' },
  { label = 'Challenges',     slug = 'challenges' },
  { label = 'Charge Shrines', slug = 'charge_shrines' },
  { label = 'Chests',         slug = 'chests' },
  { label = 'Greed Shrines',  slug = 'greed_shrines', aliases = { 'green_shrines' } },
  { label = 'Magnet Shrines', slug = 'magnet_shrines' },
  { label = 'Microwaves',     slug = 'microwaves' },
  { label = 'Moais',          slug = 'moais' },
  { label = 'Pots',           slug = 'pots' },
  { label = 'Shady Guy',      slug = 'shady_guy' },
}

local function readMonoString(ptr)
  if not ptr or ptr == 0 then
    return nil
  end

  local len = readInteger(ptr + 0x10)
  if not len or len < 0 or len > 512 then
    return nil
  end

  local ok, s = pcall(readString, ptr + 0x14, len * 2, true)
  if ok then
    return s
  end

  return nil
end

local function safeUnregister(name)
  pcall(unregisterSymbol, name)
end

local function clearRegisteredSymbols()
  for i = #state.registered, 1, -1 do
    safeUnregister(state.registered[i])
    state.registered[i] = nil
  end
end

local function registerTrackedSymbol(name, address)
  safeUnregister(name)
  registerSymbol(name, address, true)
  state.registered[#state.registered + 1] = name
end

local function registerContainerSymbols(slug, container)
  registerTrackedSymbol(('ib_%s_container'):format(slug), container)
  registerTrackedSymbol(('ib_%s_max'):format(slug), container + 0x10)
  registerTrackedSymbol(('ib_%s_current'):format(slug), container + 0x14)
end

local function findInteractablesMap()
  if not getAddressSafe('GameAssembly.dll') then
    return {}, { soft_warning = 'GameAssembly.dll is not loaded yet' }
  end

  local typeInfoAddr = getAddressSafe('GameAssembly.dll+2FB5E68')
  if not typeInfoAddr then
    return {}, { soft_warning = 'InteractablesStatus_TypeInfo is not available yet' }
  end

  local classptr = readQword(typeInfoAddr)
  if not classptr or classptr == 0 then
    return {}, { soft_warning = 'InteractablesStatus class pointer is null' }
  end

  local staticFields = readQword(classptr + 0xB8)
  if not staticFields or staticFields == 0 then
    return {}, { soft_warning = 'InteractablesStatus.static_fields is null' }
  end

  local dict = readQword(staticFields + 0x0)
  if not dict or dict == 0 then
    return {}, { soft_warning = 'InteractablesStatus.interactablesByName is null' }
  end

  local entries = readQword(dict + 0x18)
  local count = readInteger(dict + 0x20)

  if not entries or entries == 0 then
    return {}, { soft_warning = 'interactablesByName.entries is null' }
  end

  if not count or count < 0 or count > 4096 then
    error('interactablesByName.count is invalid: ' .. tostring(count))
  end

  local found = {}

  for i = 0, count - 1 do
    local entry = entries + 0x20 + (i * 0x18)
    local keyPtr = readQword(entry + 0x8)
    local valuePtr = readQword(entry + 0x10)

    if keyPtr and keyPtr ~= 0 and valuePtr and valuePtr ~= 0 then
      local label = readMonoString(keyPtr)
      if label and label ~= '' then
        found[label] = valuePtr
      end
    end
  end

  return found, { entry_count = count }
end

local function buildSnapshot(found, meta)
  local parts = {}
  parts[#parts + 1] = 'warn=' .. tostring(meta and meta.soft_warning or '')

  for _, target in ipairs(TARGETS) do
    local container = found[target.label] or 0
    parts[#parts + 1] = target.slug .. '=' .. string.format('%X', container)
  end

  return table.concat(parts, '|')
end

local function syncSymbols(found)
  clearRegisteredSymbols()

  for _, target in ipairs(TARGETS) do
    local container = found[target.label]
    if container and container ~= 0 then
      registerContainerSymbols(target.slug, container)

      if target.aliases then
        for _, aliasSlug in ipairs(target.aliases) do
          registerContainerSymbols(aliasSlug, container)
        end
      end
    end
  end
end

local function buildLog(found, meta)
  local lines = {}
  local missing = {}
  local present = 0

  lines[#lines + 1] = 'Megabonk interactables refresh:'

  for _, target in ipairs(TARGETS) do
    local container = found[target.label]
    if container and container ~= 0 then
      present = present + 1
      lines[#lines + 1] = ('%-15s | container=0x%X | current=0x%X (%d) | max=0x%X (%d)')
        :format(
          target.label,
          container,
          container + 0x14,
          readInteger(container + 0x14) or -1,
          container + 0x10,
          readInteger(container + 0x10) or -1
        )
    else
      missing[#missing + 1] = target.label
    end
  end

  lines[#lines + 1] = ('Found %d/%d target keys'):format(present, #TARGETS)

  if meta and meta.soft_warning then
    lines[#lines + 1] = 'Warning: ' .. meta.soft_warning
  end

  if #missing > 0 then
    lines[#lines + 1] = 'Missing: ' .. table.concat(missing, ', ')
  end

  return table.concat(lines, '\n')
end

local function refreshOnce()
  local found, meta = findInteractablesMap()
  local snapshot = buildSnapshot(found, meta)
  local changed = snapshot ~= state.lastSnapshot

  if changed then
    syncSymbols(found)
    state.lastSnapshot = snapshot
    print(buildLog(found, meta))
  elseif not state.didInitialPrint then
    print(buildLog(found, meta))
  end

  state.didInitialPrint = true
  state.lastRuntimeError = nil
end

local function refreshSafely()
  local ok, err = pcall(refreshOnce)
  if ok then
    return
  end

  clearRegisteredSymbols()

  local msg = '[Megabonk][Interactables] Critical refresh error: ' .. tostring(err)
  if state.lastRuntimeError ~= msg then
    print(msg)
    state.lastRuntimeError = msg
  end
end

local timer = createTimer(nil, false)
timer.Interval = REFRESH_INTERVAL_MS
timer.OnTimer = function()
  refreshSafely()
end
timer.Enabled = true
state.timer = timer

local ok, err = pcall(refreshOnce)
if not ok then
  clearRegisteredSymbols()
  if state.timer then
    state.timer.Enabled = false
    state.timer.destroy()
    state.timer = nil
  end
  error(tostring(err))
end

return
{$asm}

[DISABLE]
{$lua}
if syntaxcheck then return end

local STATE_KEY = '__megabonk_interactables_state'
local state = _G[STATE_KEY]

local function safeUnregister(name)
  pcall(unregisterSymbol, name)
end

if state then
  if state.timer then
    pcall(function()
      state.timer.Enabled = false
      state.timer.destroy()
    end)
    state.timer = nil
  end

  if state.registered then
    for i = #state.registered, 1, -1 do
      safeUnregister(state.registered[i])
      state.registered[i] = nil
    end
  end

  state.lastSnapshot = nil
  state.didInitialPrint = false
  state.lastRuntimeError = nil
end

return
{$asm}
