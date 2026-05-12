using System;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;

namespace BonkHook;

internal static unsafe class HookExports
{
    private const nuint AlwaysManagerUpdateOffset = 0x4F7520;
    private const nuint GenerateMapMoveNextOffset = 0x4A26F0;
    private const nuint MapControllerRestartRunOffset = 0x4220B0;
    private const nuint SaveManagerGetInstanceOffset = 0x525700;
    private const nuint SaveManagerSaveConfigOffset = 0x524CC0;
    private const nuint CurrentSettingsBetterUpdateCfSettingsOffset = 0x366150;
    private const nuint CurrentSettingsBetterUpdateCfSettingsMethodInfoOffset = 0x2FB38A8;
    private const nuint MapControllerTypeInfoOffset = 0x2F58E08;
    private const nuint MapGenerationControllerTypeInfoOffset = 0x2F59000;
    private const nuint AlwaysManagerTypeInfoOffset = 0x2F6BAA8;
    private const nuint CurrentSettingsTypeInfoOffset = 0x2F82E88;
    private const int ClassStaticFieldsOffset = 0xB8;
    private const int AlwaysManagerInstanceOffset = 0x0;
    private const int CurrentSettingsInstanceOffset = 0x0;
    private const int MapControllerCurrentMapOffset = 0x10;
    private const int MapControllerCurrentStageOffset = 0x18;
    private const int MapGenerationIsGeneratingOffset = 0x10;
    private const int SaveManagerConfigOffset = 0x20;
    private const int ConfigSaveFileGameSettingsOffset = 0x18;
    private const int CFGameSettingsAutoSelectUpgradesOffset = 0x68;
    private const int CFGameSettingsSkipChestAnimationOffset = 0x78;
    private const int MH_OK = 0;
    private const int MH_ERROR_ALREADY_INITIALIZED = 1;
    private const int MH_ERROR_ENABLED = 5;
    private const int ToggleSettingSkipChestAnimation = 1;
    private const int ToggleSettingAutoSelectUpgrades = 2;

    private static readonly byte[] ExpectedAlwaysManagerUpdateBytes =
    [
        0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
        0xEC, 0x20, 0x80, 0x3D, 0x64, 0xB8, 0xC7, 0x02,
    ];

    private static IntPtr _originalAlwaysManagerUpdate;
    private static IntPtr _originalGenerateMapMoveNext;
    private static IntPtr _gameAssembly;
    private static IntPtr _mapControllerRestartRun;
    private static IntPtr _saveManagerGetInstance;
    private static IntPtr _saveManagerSaveConfig;
    private static IntPtr _currentSettingsBetterUpdateCfSettings;
    private static IntPtr _currentSettingsBetterUpdateCfSettingsMethodInfo;
    private static IntPtr _il2CppStringNew;
    private static IntPtr _il2CppValueBox;
    private static IntPtr _il2CppGetCorlib;
    private static IntPtr _il2CppClassFromName;
    private static IntPtr _systemInt32Class;
    private static int _installed;
    private static int _restartRunRequested;
    private static int _snapshotReady;
    private static int _toggleSettingRequest;
    private static int _toggleSettingResult;

    [UnmanagedCallersOnly(EntryPoint = "Initialize")]
    public static uint Initialize(IntPtr _)
    {
        if (Interlocked.Exchange(ref _installed, 1) == 1)
        {
            return 0;
        }

        try
        {
            IntPtr gameAssembly = GetModuleHandleW("GameAssembly.dll");
            if (gameAssembly == IntPtr.Zero)
            {
                _installed = 0;
                return 10;
            }

            IntPtr alwaysManagerUpdate = gameAssembly + (nint)AlwaysManagerUpdateOffset;
            IntPtr generateMapMoveNext = gameAssembly + (nint)GenerateMapMoveNextOffset;
            _gameAssembly = gameAssembly;
            _mapControllerRestartRun = gameAssembly + (nint)MapControllerRestartRunOffset;
            _saveManagerGetInstance = gameAssembly + (nint)SaveManagerGetInstanceOffset;
            _saveManagerSaveConfig = gameAssembly + (nint)SaveManagerSaveConfigOffset;
            if (!HasExpectedBytes(alwaysManagerUpdate, ExpectedAlwaysManagerUpdateBytes))
            {
                _installed = 0;
                ClearResolvedGamePointers();
                return 11;
            }

            if (!IsAlwaysManagerReady(gameAssembly))
            {
                _installed = 0;
                ClearResolvedGamePointers();
                return 12;
            }

            int status = MH_Initialize();
            if (status != MH_OK && status != MH_ERROR_ALREADY_INITIALIZED)
            {
                _installed = 0;
                return (uint)(20 + status);
            }

            IntPtr detour = (IntPtr)(delegate* unmanaged<IntPtr, IntPtr, void>)&AlwaysManagerUpdateHook;
            status = MH_CreateHook(alwaysManagerUpdate, detour, out _originalAlwaysManagerUpdate);
            if (status != MH_OK)
            {
                _installed = 0;
                return (uint)(40 + status);
            }

            IntPtr generateMapDetour = (IntPtr)(delegate* unmanaged<IntPtr, IntPtr, byte>)&GenerateMapMoveNextHook;
            status = MH_CreateHook(generateMapMoveNext, generateMapDetour, out _originalGenerateMapMoveNext);
            if (status != MH_OK)
            {
                _installed = 0;
                ClearResolvedGamePointers();
                return (uint)(50 + status);
            }

            status = MH_EnableHook(IntPtr.Zero);
            if (status != MH_OK && status != MH_ERROR_ENABLED)
            {
                _installed = 0;
                ClearResolvedGamePointers();
                return (uint)(60 + status);
            }

            return 0;
        }
        catch
        {
            _installed = 0;
            return 0xE0000001;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "Uninitialize")]
    public static uint Uninitialize(IntPtr _)
    {
        try
        {
            MH_DisableHook(IntPtr.Zero);
            MH_Uninitialize();
            _installed = 0;
            ClearResolvedGamePointers();
            Interlocked.Exchange(ref _restartRunRequested, 0);
            Interlocked.Exchange(ref _snapshotReady, 0);
            Interlocked.Exchange(ref _toggleSettingRequest, 0);
            Interlocked.Exchange(ref _toggleSettingResult, 0);
            return 0;
        }
        catch
        {
            return 0xE0000002;
        }
    }

    [UnmanagedCallersOnly(EntryPoint = "RequestRestartRun")]
    public static uint RequestRestartRun(IntPtr _)
    {
        if (Volatile.Read(ref _installed) == 0)
        {
            return 100;
        }

        Interlocked.Exchange(ref _snapshotReady, 0);
        Interlocked.Exchange(ref _restartRunRequested, 1);
        return 0;
    }

    [UnmanagedCallersOnly(EntryPoint = "WaitForSnapshotReady")]
    public static uint WaitForSnapshotReady(IntPtr _)
    {
        if (Volatile.Read(ref _installed) == 0)
        {
            return 100;
        }

        return Interlocked.Exchange(ref _snapshotReady, 0) != 0 ? 1u : 0u;
    }

    [UnmanagedCallersOnly(EntryPoint = "ToggleSkipChestAnimation")]
    public static uint ToggleSkipChestAnimation(IntPtr _)
    {
        return QueueToggleSetting(ToggleSettingSkipChestAnimation);
    }

    [UnmanagedCallersOnly(EntryPoint = "ToggleAutoSelectUpgrades")]
    public static uint ToggleAutoSelectUpgrades(IntPtr _)
    {
        return QueueToggleSetting(ToggleSettingAutoSelectUpgrades);
    }

    [UnmanagedCallersOnly]
    private static void AlwaysManagerUpdateHook(IntPtr instance, IntPtr method)
    {
        var original = (delegate* unmanaged<IntPtr, IntPtr, void>)_originalAlwaysManagerUpdate;
        original(instance, method);
        try
        {
            DrainMainThreadRequests();
        }
        catch
        {
        }
    }

    [UnmanagedCallersOnly]
    private static byte GenerateMapMoveNextHook(IntPtr instance, IntPtr method)
    {
        var original = (delegate* unmanaged<IntPtr, IntPtr, byte>)_originalGenerateMapMoveNext;
        byte result = original(instance, method);
        if (result != 0)
        {
            return result;
        }

        try
        {
            if (IsMapSnapshotReady())
            {
                Interlocked.Exchange(ref _snapshotReady, 1);
            }
        }
        catch
        {
        }

        return result;
    }

    private static void DrainMainThreadRequests()
    {
        if (Interlocked.Exchange(ref _restartRunRequested, 0) == 0)
        {
        }
        else
        {
            IntPtr restartRun = _mapControllerRestartRun;
            if (restartRun == IntPtr.Zero)
            {
                IntPtr gameAssembly = GetModuleHandleW("GameAssembly.dll");
                if (gameAssembly == IntPtr.Zero)
                {
                    return;
                }

                restartRun = gameAssembly + (nint)MapControllerRestartRunOffset;
                _mapControllerRestartRun = restartRun;
            }

            var restartRunFunc = (delegate* unmanaged<IntPtr, void>)restartRun;
            restartRunFunc(IntPtr.Zero);
        }

        int toggleRequest = Interlocked.Exchange(ref _toggleSettingRequest, 0);
        if (toggleRequest != 0)
        {
            int toggleResult = ToggleSettingOnMainThread(toggleRequest);
            Interlocked.Exchange(ref _toggleSettingResult, toggleResult);
        }
    }

    private static uint QueueToggleSetting(int toggleKind)
    {
        if (Volatile.Read(ref _installed) == 0)
        {
            return 100;
        }

        if (toggleKind == 0)
        {
            return 110;
        }

        Interlocked.Exchange(ref _toggleSettingResult, 0);
        Interlocked.Exchange(ref _toggleSettingRequest, toggleKind);

        for (int i = 0; i < 200; i++)
        {
            int result = Volatile.Read(ref _toggleSettingResult);
            if (result != 0)
            {
                return (uint)result;
            }
            Thread.Sleep(5);
        }

        Interlocked.CompareExchange(ref _toggleSettingRequest, 0, toggleKind);
        return 120;
    }

    private static int ToggleSettingOnMainThread(int toggleKind)
    {
        IntPtr saveManager = GetSaveManagerInstance();
        if (saveManager == IntPtr.Zero)
        {
            return 130;
        }

        IntPtr config = *(IntPtr*)((byte*)saveManager + SaveManagerConfigOffset);
        if (config == IntPtr.Zero)
        {
            return 131;
        }

        IntPtr gameSettings = *(IntPtr*)((byte*)config + ConfigSaveFileGameSettingsOffset);
        if (gameSettings == IntPtr.Zero)
        {
            return 132;
        }

        int fieldOffset = toggleKind switch
        {
            ToggleSettingSkipChestAnimation => CFGameSettingsSkipChestAnimationOffset,
            ToggleSettingAutoSelectUpgrades => CFGameSettingsAutoSelectUpgradesOffset,
            _ => 0,
        };
        if (fieldOffset == 0)
        {
            return 133;
        }

        int currentValue = *(int*)((byte*)gameSettings + fieldOffset);
        int toggledValue = currentValue == 0 ? 1 : 0;
        if (TryUpdateSettingThroughCurrentSettings(toggleKind, gameSettings, toggledValue))
        {
            SaveConfig(saveManager);
        }
        else
        {
            *(int*)((byte*)gameSettings + fieldOffset) = toggledValue;
            SaveConfig(saveManager);
        }

        return toggledValue != 0 ? 1 : 2;
    }

    private static bool TryUpdateSettingThroughCurrentSettings(int toggleKind, IntPtr gameSettings, int toggledValue)
    {
        IntPtr gameAssembly = ResolveGameAssembly();
        if (gameAssembly == IntPtr.Zero)
        {
            return false;
        }

        IntPtr currentSettings = GetCurrentSettingsInstance(gameAssembly);
        if (currentSettings == IntPtr.Zero)
        {
            return false;
        }

        IntPtr methodInfo = GetCurrentSettingsBetterUpdateCfSettingsMethodInfo(gameAssembly);
        if (methodInfo == IntPtr.Zero)
        {
            return false;
        }

        IntPtr settingName = CreateSettingNameString(toggleKind);
        if (settingName == IntPtr.Zero)
        {
            return false;
        }

        IntPtr boxedValue = BoxInt32(toggledValue);
        if (boxedValue == IntPtr.Zero)
        {
            return false;
        }

        IntPtr betterUpdate = _currentSettingsBetterUpdateCfSettings;
        if (betterUpdate == IntPtr.Zero)
        {
            betterUpdate = gameAssembly + (nint)CurrentSettingsBetterUpdateCfSettingsOffset;
            _currentSettingsBetterUpdateCfSettings = betterUpdate;
        }

        var betterUpdateFunc = (delegate* unmanaged<IntPtr, IntPtr, IntPtr, IntPtr, IntPtr, void>)betterUpdate;
        betterUpdateFunc(currentSettings, settingName, boxedValue, gameSettings, methodInfo);
        return true;
    }

    private static IntPtr GetCurrentSettingsInstance(IntPtr gameAssembly)
    {
        IntPtr currentSettingsStaticFields = ReadStaticFields(gameAssembly, CurrentSettingsTypeInfoOffset);
        if (currentSettingsStaticFields == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        return *(IntPtr*)((byte*)currentSettingsStaticFields + CurrentSettingsInstanceOffset);
    }

    private static IntPtr GetCurrentSettingsBetterUpdateCfSettingsMethodInfo(IntPtr gameAssembly)
    {
        IntPtr methodInfo = _currentSettingsBetterUpdateCfSettingsMethodInfo;
        if (methodInfo != IntPtr.Zero)
        {
            return methodInfo;
        }

        IntPtr methodInfoStorage = gameAssembly + (nint)CurrentSettingsBetterUpdateCfSettingsMethodInfoOffset;
        methodInfo = *(IntPtr*)methodInfoStorage;
        _currentSettingsBetterUpdateCfSettingsMethodInfo = methodInfo;
        return methodInfo;
    }

    private static IntPtr CreateSettingNameString(int toggleKind)
    {
        ReadOnlySpan<byte> name = toggleKind switch
        {
            ToggleSettingSkipChestAnimation => "skip_chest_animation"u8,
            ToggleSettingAutoSelectUpgrades => "auto_select_upgrades"u8,
            _ => default,
        };
        if (name.IsEmpty)
        {
            return IntPtr.Zero;
        }

        IntPtr stringNew = ResolveIl2CppExport(ref _il2CppStringNew, "il2cpp_string_new");
        if (stringNew == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        Span<byte> nullTerminatedName = stackalloc byte[name.Length + 1];
        name.CopyTo(nullTerminatedName);
        fixed (byte* namePtr = nullTerminatedName)
        {
            var stringNewFunc = (delegate* unmanaged<byte*, IntPtr>)stringNew;
            return stringNewFunc(namePtr);
        }
    }

    private static IntPtr BoxInt32(int value)
    {
        IntPtr int32Class = GetSystemInt32Class();
        if (int32Class == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        IntPtr valueBox = ResolveIl2CppExport(ref _il2CppValueBox, "il2cpp_value_box");
        if (valueBox == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        int valueToBox = value;
        var valueBoxFunc = (delegate* unmanaged<IntPtr, void*, IntPtr>)valueBox;
        return valueBoxFunc(int32Class, &valueToBox);
    }

    private static IntPtr GetSystemInt32Class()
    {
        IntPtr int32Class = _systemInt32Class;
        if (int32Class != IntPtr.Zero)
        {
            return int32Class;
        }

        IntPtr getCorlib = ResolveIl2CppExport(ref _il2CppGetCorlib, "il2cpp_get_corlib");
        IntPtr classFromName = ResolveIl2CppExport(ref _il2CppClassFromName, "il2cpp_class_from_name");
        if (getCorlib == IntPtr.Zero || classFromName == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        var getCorlibFunc = (delegate* unmanaged<IntPtr>)getCorlib;
        IntPtr corlib = getCorlibFunc();
        if (corlib == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        ReadOnlySpan<byte> namespaceName = "System"u8;
        ReadOnlySpan<byte> className = "Int32"u8;
        Span<byte> nullTerminatedNamespace = stackalloc byte[namespaceName.Length + 1];
        Span<byte> nullTerminatedClassName = stackalloc byte[className.Length + 1];
        namespaceName.CopyTo(nullTerminatedNamespace);
        className.CopyTo(nullTerminatedClassName);

        fixed (byte* namespacePtr = nullTerminatedNamespace)
        fixed (byte* classNamePtr = nullTerminatedClassName)
        {
            var classFromNameFunc = (delegate* unmanaged<IntPtr, byte*, byte*, IntPtr>)classFromName;
            int32Class = classFromNameFunc(corlib, namespacePtr, classNamePtr);
        }

        _systemInt32Class = int32Class;
        return int32Class;
    }

    private static IntPtr GetSaveManagerInstance()
    {
        IntPtr getInstance = _saveManagerGetInstance;
        if (getInstance == IntPtr.Zero)
        {
            IntPtr gameAssembly = _gameAssembly;
            if (gameAssembly == IntPtr.Zero)
            {
                gameAssembly = GetModuleHandleW("GameAssembly.dll");
                if (gameAssembly == IntPtr.Zero)
                {
                    return IntPtr.Zero;
                }

                _gameAssembly = gameAssembly;
            }

            getInstance = gameAssembly + (nint)SaveManagerGetInstanceOffset;
            _saveManagerGetInstance = getInstance;
        }

        var getInstanceFunc = (delegate* unmanaged<IntPtr>)getInstance;
        return getInstanceFunc();
    }

    private static void SaveConfig(IntPtr saveManager)
    {
        IntPtr saveConfig = _saveManagerSaveConfig;
        if (saveConfig == IntPtr.Zero)
        {
            IntPtr gameAssembly = ResolveGameAssembly();
            if (gameAssembly == IntPtr.Zero)
            {
                return;
            }

            saveConfig = gameAssembly + (nint)SaveManagerSaveConfigOffset;
            _saveManagerSaveConfig = saveConfig;
        }

        var saveConfigFunc = (delegate* unmanaged<IntPtr, IntPtr, void>)saveConfig;
        saveConfigFunc(saveManager, IntPtr.Zero);
    }

    private static bool IsMapSnapshotReady()
    {
        IntPtr gameAssembly = ResolveGameAssembly();
        if (gameAssembly == IntPtr.Zero)
        {
            return false;
        }

        IntPtr mapGenerationStaticFields = ReadStaticFields(gameAssembly, MapGenerationControllerTypeInfoOffset);
        if (mapGenerationStaticFields == IntPtr.Zero)
        {
            return false;
        }

        bool isGenerating = *(byte*)((byte*)mapGenerationStaticFields + MapGenerationIsGeneratingOffset) != 0;
        if (isGenerating)
        {
            return false;
        }

        IntPtr mapControllerStaticFields = ReadStaticFields(gameAssembly, MapControllerTypeInfoOffset);
        if (mapControllerStaticFields == IntPtr.Zero)
        {
            return false;
        }

        IntPtr currentMap = *(IntPtr*)((byte*)mapControllerStaticFields + MapControllerCurrentMapOffset);
        IntPtr currentStage = *(IntPtr*)((byte*)mapControllerStaticFields + MapControllerCurrentStageOffset);
        return currentMap != IntPtr.Zero && currentStage != IntPtr.Zero;
    }

    private static bool IsAlwaysManagerReady(IntPtr gameAssembly)
    {
        IntPtr alwaysManagerStaticFields = ReadStaticFields(gameAssembly, AlwaysManagerTypeInfoOffset);
        if (alwaysManagerStaticFields == IntPtr.Zero)
        {
            return false;
        }

        IntPtr instance = *(IntPtr*)((byte*)alwaysManagerStaticFields + AlwaysManagerInstanceOffset);
        return instance != IntPtr.Zero;
    }

    private static IntPtr ResolveGameAssembly()
    {
        IntPtr gameAssembly = _gameAssembly;
        if (gameAssembly != IntPtr.Zero)
        {
            return gameAssembly;
        }

        gameAssembly = GetModuleHandleW("GameAssembly.dll");
        if (gameAssembly != IntPtr.Zero)
        {
            _gameAssembly = gameAssembly;
        }

        return gameAssembly;
    }

    private static IntPtr ResolveIl2CppExport(ref IntPtr cachedExport, string exportName)
    {
        IntPtr export = cachedExport;
        if (export != IntPtr.Zero)
        {
            return export;
        }

        IntPtr gameAssembly = ResolveGameAssembly();
        if (gameAssembly == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        export = GetProcAddress(gameAssembly, exportName);
        if (export != IntPtr.Zero)
        {
            cachedExport = export;
        }

        return export;
    }

    private static void ClearResolvedGamePointers()
    {
        _gameAssembly = IntPtr.Zero;
        _mapControllerRestartRun = IntPtr.Zero;
        _saveManagerGetInstance = IntPtr.Zero;
        _saveManagerSaveConfig = IntPtr.Zero;
        _currentSettingsBetterUpdateCfSettings = IntPtr.Zero;
        _currentSettingsBetterUpdateCfSettingsMethodInfo = IntPtr.Zero;
        _il2CppStringNew = IntPtr.Zero;
        _il2CppValueBox = IntPtr.Zero;
        _il2CppGetCorlib = IntPtr.Zero;
        _il2CppClassFromName = IntPtr.Zero;
        _systemInt32Class = IntPtr.Zero;
    }

    private static IntPtr ReadStaticFields(IntPtr gameAssembly, nuint typeInfoOffset)
    {
        IntPtr typeInfoAddress = gameAssembly + (nint)typeInfoOffset;
        IntPtr classPtr = *(IntPtr*)typeInfoAddress;
        if (classPtr == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        return *(IntPtr*)((byte*)classPtr + ClassStaticFieldsOffset);
    }

    private static bool HasExpectedBytes(IntPtr address, byte[] expectedBytes)
    {
        byte* p = (byte*)address;
        for (int i = 0; i < expectedBytes.Length; i++)
        {
            if (p[i] != expectedBytes[i])
            {
                return false;
            }
        }

        return true;
    }

    [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandleW(string lpModuleName);

    [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Ansi)]
    private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

    [DllImport("MinHook.x64.dll", ExactSpelling = true)]
    private static extern int MH_Initialize();

    [DllImport("MinHook.x64.dll", ExactSpelling = true)]
    private static extern int MH_Uninitialize();

    [DllImport("MinHook.x64.dll", ExactSpelling = true)]
    private static extern int MH_CreateHook(
        IntPtr pTarget,
        IntPtr pDetour,
        out IntPtr ppOriginal);

    [DllImport("MinHook.x64.dll", ExactSpelling = true)]
    private static extern int MH_EnableHook(IntPtr pTarget);

    [DllImport("MinHook.x64.dll", ExactSpelling = true)]
    private static extern int MH_DisableHook(IntPtr pTarget);
}
