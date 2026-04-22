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
    private const nuint MapControllerTypeInfoOffset = 0x2F58E08;
    private const nuint MapGenerationControllerTypeInfoOffset = 0x2F59000;
    private const int ClassStaticFieldsOffset = 0xB8;
    private const int MapControllerCurrentMapOffset = 0x10;
    private const int MapControllerCurrentStageOffset = 0x18;
    private const int MapGenerationIsGeneratingOffset = 0x10;
    private const int MH_OK = 0;
    private const int MH_ERROR_ALREADY_INITIALIZED = 1;
    private const int MH_ERROR_ENABLED = 5;

    private static readonly byte[] ExpectedAlwaysManagerUpdateBytes =
    [
        0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
        0xEC, 0x20, 0x80, 0x3D, 0x64, 0xB8, 0xC7, 0x02,
    ];

    private static IntPtr _originalAlwaysManagerUpdate;
    private static IntPtr _originalGenerateMapMoveNext;
    private static IntPtr _gameAssembly;
    private static IntPtr _mapControllerRestartRun;
    private static int _installed;
    private static int _restartRunRequested;
    private static int _snapshotReady;

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
            if (!HasExpectedBytes(alwaysManagerUpdate, ExpectedAlwaysManagerUpdateBytes))
            {
                _installed = 0;
                _gameAssembly = IntPtr.Zero;
                _mapControllerRestartRun = IntPtr.Zero;
                return 11;
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
                _gameAssembly = IntPtr.Zero;
                _mapControllerRestartRun = IntPtr.Zero;
                return (uint)(50 + status);
            }

            status = MH_EnableHook(IntPtr.Zero);
            if (status != MH_OK && status != MH_ERROR_ENABLED)
            {
                _installed = 0;
                _gameAssembly = IntPtr.Zero;
                _mapControllerRestartRun = IntPtr.Zero;
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
            _gameAssembly = IntPtr.Zero;
            _mapControllerRestartRun = IntPtr.Zero;
            Interlocked.Exchange(ref _restartRunRequested, 0);
            Interlocked.Exchange(ref _snapshotReady, 0);
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
    public static uint WaitForSnapshotReady(IntPtr timeoutMilliseconds)
    {
        if (Volatile.Read(ref _installed) == 0)
        {
            return 100;
        }

        long timeout = Math.Clamp(timeoutMilliseconds.ToInt64(), 0, 60_000);
        long deadline = Environment.TickCount64 + timeout;
        while (true)
        {
            if (Interlocked.Exchange(ref _snapshotReady, 0) != 0)
            {
                return 1;
            }

            if (timeout == 0 || Environment.TickCount64 >= deadline)
            {
                return 0;
            }

            Thread.Sleep(5);
        }
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
            return;
        }

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

    private static bool IsMapSnapshotReady()
    {
        IntPtr gameAssembly = _gameAssembly;
        if (gameAssembly == IntPtr.Zero)
        {
            gameAssembly = GetModuleHandleW("GameAssembly.dll");
            if (gameAssembly == IntPtr.Zero)
            {
                return false;
            }

            _gameAssembly = gameAssembly;
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
