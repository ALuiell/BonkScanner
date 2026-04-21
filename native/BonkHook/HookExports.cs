using System;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Threading;

namespace BonkHook;

internal static unsafe class HookExports
{
    private const nuint AlwaysManagerUpdateOffset = 0x4EC430;
    private const int MH_OK = 0;
    private const int MH_ERROR_ALREADY_INITIALIZED = 1;
    private const int MH_ERROR_ENABLED = 5;

    private static readonly byte[] ExpectedAlwaysManagerUpdateBytes =
    [
        0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83,
        0xEC, 0x20, 0x80, 0x3D, 0x4A, 0x5A, 0xC7, 0x02,
    ];

    private static IntPtr _originalAlwaysManagerUpdate;
    private static int _installed;
    private static int _messageShown;

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

            IntPtr target = gameAssembly + (nint)AlwaysManagerUpdateOffset;
            if (!HasExpectedBytes(target))
            {
                _installed = 0;
                return 11;
            }

            int status = MH_Initialize();
            if (status != MH_OK && status != MH_ERROR_ALREADY_INITIALIZED)
            {
                _installed = 0;
                return (uint)(20 + status);
            }

            IntPtr detour = (IntPtr)(delegate* unmanaged<IntPtr, IntPtr, void>)&AlwaysManagerUpdateHook;
            status = MH_CreateHook(target, detour, out _originalAlwaysManagerUpdate);
            if (status != MH_OK)
            {
                _installed = 0;
                return (uint)(40 + status);
            }

            status = MH_EnableHook(target);
            if (status != MH_OK && status != MH_ERROR_ENABLED)
            {
                _installed = 0;
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
            return 0;
        }
        catch
        {
            return 0xE0000002;
        }
    }

    [UnmanagedCallersOnly]
    private static void AlwaysManagerUpdateHook(IntPtr instance, IntPtr method)
    {
        try
        {
            if (Interlocked.Exchange(ref _messageShown, 1) == 0)
            {
                MessageBoxW(
                    IntPtr.Zero,
                    "AlwaysManager.Update hook hit",
                    "BonkHook",
                    0);
            }
        }
        finally
        {
            var original = (delegate* unmanaged<IntPtr, IntPtr, void>)_originalAlwaysManagerUpdate;
            original(instance, method);
        }
    }

    private static bool HasExpectedBytes(IntPtr address)
    {
        byte* p = (byte*)address;
        for (int i = 0; i < ExpectedAlwaysManagerUpdateBytes.Length; i++)
        {
            if (p[i] != ExpectedAlwaysManagerUpdateBytes[i])
            {
                return false;
            }
        }

        return true;
    }

    [DllImport("kernel32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandleW(string lpModuleName);

    [DllImport("user32.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(
        IntPtr hWnd,
        string lpText,
        string lpCaption,
        uint uType);

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
