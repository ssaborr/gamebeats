#include <windows.h>
#include "MinHook.h"

/*
 * spotify_hook.dll — Minimal focus-steal prevention.
 *
 * Only hooks SetForegroundWindow — the single Win32 function responsible
 * for stealing focus from another application. All other hooks (ShowWindow,
 * CreateWindowExW, BringWindowToTop, SetActiveWindow) have been removed
 * because they interfere with Spotify's internal Electron/Chromium window
 * management and cause it to crash or exit.
 *
 * BringWindowToTop and SetActiveWindow operate within the same process and
 * do NOT steal focus from a different foreground app — they don't need to
 * be blocked.
 */

typedef BOOL (WINAPI *FN_SetForegroundWindow)(HWND);
FN_SetForegroundWindow pSetForegroundWindow = NULL;

BOOL WINAPI DetourSetForegroundWindow(HWND hWnd) {
    // Silently discard — Spotify cannot steal the foreground.
    (void)hWnd;
    return FALSE;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);

        if (MH_Initialize() != MH_OK)
            return TRUE;

        MH_CreateHookApi(L"user32.dll", "SetForegroundWindow",
                         (LPVOID)DetourSetForegroundWindow,
                         reinterpret_cast<LPVOID*>(&pSetForegroundWindow));

        MH_EnableHook(MH_ALL_HOOKS);
    }
    else if (ul_reason_for_call == DLL_PROCESS_DETACH) {
        MH_DisableHook(MH_ALL_HOOKS);
        MH_Uninitialize();
    }
    return TRUE;
}
