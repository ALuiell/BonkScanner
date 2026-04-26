if bonkLogger and bonkLogger.stop then
  bonkLogger.stop()
end

bonkLogger = {
  spawnerAddr = getAddress('GameAssembly.dll+49C2A0'),
  instantiateRetAddr = getAddress('GameAssembly.dll+49CA28'),
  instantiateTransformRetAddr = getAddress('GameAssembly.dll+49CA47'),
  instantiateAlignTransformRetAddr = getAddress('GameAssembly.dll+49CB70'),
  startAddr = getAddress('GameAssembly.dll+4BFE00'),
  startTransformRetAddr1 = getAddress('GameAssembly.dll+4BFE72'),
  startTransformRetAddr2 = getAddress('GameAssembly.dll+4BFEB2'),
  startTransformRetAddr3 = getAddress('GameAssembly.dll+4BFF00'),
  lateCallAddr = getAddress('GameAssembly.dll+4C0032'),
  logPath = os.getenv('TEMP') .. '\\bonk_interactable_log_v5.csv',
  file = nil,
  seq = 0,
  run = 0,
  active = false,
  maxEvents = 25000,
  flushEvery = 128,
  rowsSinceFlush = 0,
}

local function hex(v)
  v = tonumber(v) or 0
  return string.format('0x%X', v)
end

local function csv(v)
  v = tostring(v or '')
  if v:find('[,"\r\n]') then
    v = '"' .. v:gsub('"', '""') .. '"'
  end
  return v
end

local function appendRow(cols)
  local f = bonkLogger.file
  if not f then
    f = io.open(bonkLogger.logPath, 'a')
    bonkLogger.file = f
  end

  if not f then
    return false
  end

  local out = {}
  for i = 1, #cols do
    out[i] = csv(cols[i])
  end
  f:write(table.concat(out, ',') .. '\r\n')
  bonkLogger.rowsSinceFlush = bonkLogger.rowsSinceFlush + 1
  if bonkLogger.rowsSinceFlush >= bonkLogger.flushEvery then
    f:flush()
    bonkLogger.rowsSinceFlush = 0
  end

  return true
end

local function safeReadPointer(addr)
  local ok, v = pcall(readPointer, addr)
  return ok and (v or 0) or 0
end

local function safeReadInteger(addr)
  local ok, v = pcall(readInteger, addr)
  return ok and (v or 0) or 0
end

local function safeReadQword(addr)
  local ok, v = pcall(readQword, addr)
  return ok and (v or 0) or 0
end

local function safeReadFloat(addr)
  local ok, v = pcall(readFloat, addr)
  return ok and (v or 0) or 0
end

local function readIl2CppString(strPtr)
  if strPtr == 0 then
    return ''
  end

  local len = safeReadInteger(strPtr + 0x10)
  if len <= 0 or len > 256 then
    return ''
  end

  local ok, s = pcall(readString, strPtr + 0x14, len * 2, true)
  return ok and (s or '') or ''
end

local function readPrefabList(prefabsArray)
  if prefabsArray == 0 then
    return 0, ''
  end

  local len = tonumber(safeReadQword(prefabsArray + 0x18)) or 0
  if len < 0 then len = 0 end
  if len > 32 then len = 32 end

  local items = {}
  for i = 0, len - 1 do
    local prefab = safeReadPointer(prefabsArray + 0x20 + (i * 8))
    items[#items + 1] = hex(prefab)
  end

  return len, table.concat(items, ';')
end

local function removeLoggerBreakpoints()
  pcall(debug_removeBreakpoint, bonkLogger.spawnerAddr)
  pcall(debug_removeBreakpoint, bonkLogger.instantiateRetAddr)
  pcall(debug_removeBreakpoint, bonkLogger.instantiateTransformRetAddr)
  pcall(debug_removeBreakpoint, bonkLogger.instantiateAlignTransformRetAddr)
  pcall(debug_removeBreakpoint, bonkLogger.startAddr)
  pcall(debug_removeBreakpoint, bonkLogger.startTransformRetAddr1)
  pcall(debug_removeBreakpoint, bonkLogger.startTransformRetAddr2)
  pcall(debug_removeBreakpoint, bonkLogger.startTransformRetAddr3)
  pcall(debug_removeBreakpoint, bonkLogger.lateCallAddr)
end

local function appendErrorRow(rip, err)
  pcall(appendRow, {
    os.date('%Y-%m-%d %H:%M:%S'),
    bonkLogger.run,
    bonkLogger.seq,
    'error',
    hex(rip),
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    tostring(err),
    ''
  })
end

local function appendGeneric(eventName, label, notes)
  local returnAddr = safeReadPointer(RSP)
  appendRow({
    os.date('%Y-%m-%d %H:%M:%S'),
    bonkLogger.run,
    bonkLogger.seq,
    eventName,
    hex(RIP),
    hex(returnAddr),
    hex(RAX),
    hex(RBX),
    hex(RCX),
    hex(RDX),
    hex(RSI),
    hex(RDI),
    hex(R8),
    hex(R9),
    label or '',
    notes or ''
  })
end

local function logSpawnerHit()
  local randomObject = tonumber(RDX) or 0
  local callerIndex = tonumber(RBX) or 0

  local amount = 0
  local maxAmount = 0
  local checkRadius = 0
  local scaleMin = 0
  local scaleMax = 0
  local maxSlopeAngle = 0
  local upOffset = 0
  local prefabsArray = 0
  local prefabsLen = 0
  local prefabsJoined = ''
  local alignWithNormal = 0

  if randomObject ~= 0 then
    amount = safeReadInteger(randomObject + 0x10)
    maxAmount = safeReadInteger(randomObject + 0x14)
    checkRadius = safeReadFloat(randomObject + 0x18)
    scaleMin = safeReadFloat(randomObject + 0x1C)
    scaleMax = safeReadFloat(randomObject + 0x20)
    maxSlopeAngle = safeReadFloat(randomObject + 0x24)
    upOffset = safeReadFloat(randomObject + 0x28)
    prefabsArray = safeReadPointer(randomObject + 0x30)
    prefabsLen, prefabsJoined = readPrefabList(prefabsArray)
    alignWithNormal = safeReadInteger(randomObject + 0x44)
  end

  local notes = table.concat({
    'caller_index=' .. tostring(callerIndex),
    'amount=' .. tostring(amount),
    'maxAmount=' .. tostring(maxAmount),
    string.format('checkRadius=%.3f', checkRadius),
    string.format('scaleMin=%.3f', scaleMin),
    string.format('scaleMax=%.3f', scaleMax),
    string.format('maxSlopeAngle=%.3f', maxSlopeAngle),
    string.format('upOffset=%.3f', upOffset),
    'prefabs_ptr=' .. hex(prefabsArray),
    'prefabs_len=' .. tostring(prefabsLen),
    'align=' .. tostring(alignWithNormal)
  }, ';')

  appendGeneric('spawner', prefabsJoined, notes)
end

local function logInstantiateReturn()
  local prefab = tonumber(RDI) or 0
  local instance = tonumber(RAX) or 0
  local notes = table.concat({
    'prefab=' .. hex(prefab),
    'instance=' .. hex(instance),
    'instance_deref=' .. hex(safeReadPointer(instance)),
    'rbx=' .. hex(RBX),
    'rsi=' .. hex(RSI)
  }, ';')

  appendGeneric('instret', hex(prefab), notes)
end

local function logInstantiateTransform()
  local gameObject = tonumber(RDI) or 0
  local transform = tonumber(RAX) or 0
  local notes = table.concat({
    'gameObject=' .. hex(gameObject),
    'transform=' .. hex(transform),
    'transform_deref=' .. hex(safeReadPointer(transform)),
    'rbx=' .. hex(RBX),
    'rsi=' .. hex(RSI)
  }, ';')

  appendGeneric('inst_transform', hex(transform), notes)
end

local function logStart()
  local component = tonumber(RCX) or 0

  local notes = table.concat({
    'start_component=' .. hex(component),
    'component_deref=' .. hex(safeReadPointer(component)),
    'rbx=' .. hex(RBX),
    'rdi=' .. hex(RDI)
  }, ';')

  appendGeneric('start', hex(component), notes)
end

local function logStartTransform(slot)
  local component = tonumber(RBX) or 0
  local transform = tonumber(RAX) or 0
  local notes = table.concat({
    'start_component=' .. hex(component),
    'component_deref=' .. hex(safeReadPointer(component)),
    'transform=' .. hex(transform),
    'transform_deref=' .. hex(safeReadPointer(transform)),
    'slot=' .. tostring(slot)
  }, ';')

  appendGeneric('start_transform', hex(transform), notes)
end

local function logLateCall()
  local categoryPtr = tonumber(RAX) or 0
  local label = readIl2CppString(categoryPtr)
  local lateObj = tonumber(RBX) or 0
  local notes = table.concat({
    'category_ptr=' .. hex(categoryPtr),
    'late_obj=' .. hex(lateObj),
    'late_obj_deref=' .. hex(safeReadPointer(lateObj)),
    'rcx_before_call=' .. hex(RCX),
    'rdi=' .. hex(RDI)
  }, ';')

  appendGeneric('latecall', label, notes)
end

function debugger_onBreakpoint()
  if not bonkLogger or not bonkLogger.active then
    return 0
  end

  local rip = tonumber(RIP) or 0
  local handled = false

  local ok, err = pcall(function()
    if bonkLogger.seq >= bonkLogger.maxEvents then
      appendGeneric('limit', '', 'maxEvents=' .. tostring(bonkLogger.maxEvents))
      bonkLogger.active = false
      removeLoggerBreakpoints()
      handled = true
      return
    end

    if rip == bonkLogger.spawnerAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logSpawnerHit()
    elseif rip == bonkLogger.instantiateRetAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateReturn()
    elseif rip == bonkLogger.instantiateTransformRetAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform()
    elseif rip == bonkLogger.instantiateAlignTransformRetAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logInstantiateTransform()
    elseif rip == bonkLogger.startAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStart()
    elseif rip == bonkLogger.startTransformRetAddr1 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(1)
    elseif rip == bonkLogger.startTransformRetAddr2 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(2)
    elseif rip == bonkLogger.startTransformRetAddr3 then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logStartTransform(3)
    elseif rip == bonkLogger.lateCallAddr then
      handled = true
      bonkLogger.seq = bonkLogger.seq + 1
      logLateCall()
    end
  end)

  if not ok then
    appendErrorRow(rip, err)
  end

  if handled then
    debug_continueFromBreakpoint('co_run')
    return 1
  end

  return 0
end

function bonkLogger.mark(name)
  appendRow({
    os.date('%Y-%m-%d %H:%M:%S'),
    bonkLogger.run,
    bonkLogger.seq,
    'marker',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    '',
    name or '',
    ''
  })
  print('Marker: ' .. tostring(name or ''))
end

function bonkLogger.flush()
  if bonkLogger.file then
    bonkLogger.file:flush()
    bonkLogger.rowsSinceFlush = 0
  end
end

function bonkLogger.nextRun(name)
  bonkLogger.run = bonkLogger.run + 1
  bonkLogger.mark(name or ('RUN_' .. bonkLogger.run .. '_START'))
end

function bonkLogger.start(customPath)
  if customPath and customPath ~= '' then
    bonkLogger.logPath = customPath
  end

  removeLoggerBreakpoints()

  if bonkLogger.file then
    pcall(function()
      bonkLogger.file:flush()
      bonkLogger.file:close()
    end)
    bonkLogger.file = nil
  end

  local f = assert(io.open(bonkLogger.logPath, 'w'))
  f:write('ts,run,seq,event,rip,return_addr,rax,rbx,rcx,rdx,rsi,rdi,r8,r9,label,notes\r\n')
  bonkLogger.file = f

  debug_setBreakpoint(bonkLogger.spawnerAddr)
  debug_setBreakpoint(bonkLogger.instantiateRetAddr)
  debug_setBreakpoint(bonkLogger.instantiateTransformRetAddr)
  debug_setBreakpoint(bonkLogger.instantiateAlignTransformRetAddr)
  debug_setBreakpoint(bonkLogger.startAddr)
  debug_setBreakpoint(bonkLogger.startTransformRetAddr1)
  debug_setBreakpoint(bonkLogger.startTransformRetAddr2)
  debug_setBreakpoint(bonkLogger.startTransformRetAddr3)
  debug_setBreakpoint(bonkLogger.lateCallAddr)

  bonkLogger.seq = 0
  bonkLogger.run = 0
  bonkLogger.rowsSinceFlush = 0
  bonkLogger.active = true

  bonkLogger.nextRun('RUN_1_START')

  print('Bonk logger v5 started')
  print('Log: ' .. bonkLogger.logPath)
  print('Spawner: ' .. hex(bonkLogger.spawnerAddr))
  print('InstantiateRet: ' .. hex(bonkLogger.instantiateRetAddr))
  print('InstantiateTransformRet: ' .. hex(bonkLogger.instantiateTransformRetAddr))
  print('InstantiateAlignTransformRet: ' .. hex(bonkLogger.instantiateAlignTransformRetAddr))
  print('BaseInteractable.Start: ' .. hex(bonkLogger.startAddr))
  print('StartTransformRet1: ' .. hex(bonkLogger.startTransformRetAddr1))
  print('StartTransformRet2: ' .. hex(bonkLogger.startTransformRetAddr2))
  print('StartTransformRet3: ' .. hex(bonkLogger.startTransformRetAddr3))
  print('LateCall: ' .. hex(bonkLogger.lateCallAddr))
  print('No executeCodeEx is used; join inst_transform.transform to start_transform.transform')
end

function bonkLogger.stop()
  bonkLogger.active = false
  removeLoggerBreakpoints()
  if bonkLogger.file then
    pcall(function()
      bonkLogger.file:flush()
      bonkLogger.file:close()
    end)
    bonkLogger.file = nil
  end
  print('Bonk logger stopped')
  print('Log: ' .. bonkLogger.logPath)
end

bonkLogger.start()
