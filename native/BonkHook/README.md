# BonkHook

Minimal NativeAOT smoke-test hook for Megabonk IL2CPP.

Build:

```powershell
dotnet publish native\BonkHook -c Release -r win-x64
```

The publish output must contain:

- `BonkHook.dll`
- `MinHook.x64.dll`

NativeAOT on Windows requires the Visual Studio Desktop Development for C++
workload because the publish step needs the platform linker.
