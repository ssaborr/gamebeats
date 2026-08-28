// spotify_focus_guard.cpp - keep Spotify invisible and non-activating.
// No DLL injection. No hooking. Pure Win32 from outside the process.
//
// Compile with MSYS2 MinGW64:
//   g++ -o spotify_focus_guard.exe spotify_focus_guard.cpp -mwindows -static
// 
// The -mwindows flag (or /SUBSYSTEM:WINDOWS in MSVC) ensures no console is created.

#include <windows.h>
#include <tlhelp32.h>
#include <cwchar>
#include <vector>

static std::vector<DWORD> GetSpotifyPids() {
    std::vector<DWORD> pids;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return pids;

    PROCESSENTRY32W pe = {};
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            wchar_t name[MAX_PATH] = {};
            wcsncpy_s(name, pe.szExeFile, MAX_PATH - 1);
            CharLowerW(name);
            if (wcscmp(name, L"spotify.exe") == 0) {
                pids.push_back(pe.th32ProcessID);
            }
        } while (Process32NextW(snap, &pe));
    }

    CloseHandle(snap);
    return pids;
}

static bool ContainsPid(const std::vector<DWORD>& pids, DWORD pid) {
    for (DWORD item : pids) {
        if (item == pid) return true;
    }
    return false;
}

struct EnumData {
    std::vector<DWORD> pids;
};

static BOOL CALLBACK GuardSpotifyWindow(HWND hwnd, LPARAM lp) {
    EnumData* data = reinterpret_cast<EnumData*>(lp);
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (!ContainsPid(data->pids, pid)) return TRUE;

    LONG_PTR style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
    LONG_PTR new_style = style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW;
    new_style &= ~WS_EX_APPWINDOW; // Ensure it's not treated as a primary taskbar window

    if (style != new_style) {
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, new_style);
        // Notify Windows of the frame change to re-evaluate activation rules
        SetWindowPos(
            hwnd,
            HWND_BOTTOM,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE |
            SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS | SWP_FRAMECHANGED
        );
    }

    // Hide Spotify completely while GameBeats is running. Audio playback and
    // media commands keep working, but the desktop window stays off-screen,
    // out of Alt-Tab, and out of the taskbar.
    ShowWindow(hwnd, SW_HIDE);
    SetWindowPos(
        hwnd,
        HWND_BOTTOM,
        0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE |
        SWP_NOOWNERZORDER | SWP_ASYNCWINDOWPOS | SWP_HIDEWINDOW |
        SWP_FRAMECHANGED
    );

    return TRUE;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, LPSTR lpCmdLine, int nCmdShow) {
    // This is a "Windows Application" subsystem process. No console is allocated by the OS.
    // We never call CreateWindow, so the process remains completely invisible.

    // 1. Identify the parent process (GameBeats) to know when to shut down.
    DWORD ppid = 0;
    DWORD myPid = GetCurrentProcessId();
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap != INVALID_HANDLE_VALUE) {
        PROCESSENTRY32W pe = { sizeof(pe) };
        if (Process32FirstW(snap, &pe)) {
            do {
                if (pe.th32ProcessID == myPid) {
                    ppid = pe.th32ParentProcessID;
                    break;
                }
            } while (Process32NextW(snap, &pe));
        }
        CloseHandle(snap);
    }

    // 2. Open a handle with SYNCHRONIZE rights. 
    // This allows us to "Wait" on the parent process.
    HANDLE hParent = ppid ? OpenProcess(SYNCHRONIZE, FALSE, ppid) : NULL;

    for (;;) {
        // 3. Signal to stop: Check if the parent process is still alive.
        // WaitForSingleObject returns WAIT_OBJECT_0 immediately if the process has exited.
        if (hParent) {
            if (WaitForSingleObject(hParent, 0) == WAIT_OBJECT_0) {
                break; 
            }
        } else {
            // If we couldn't get a handle to the parent, we are orphaned; exit.
            break;
        }

        EnumData data;
        data.pids = GetSpotifyPids();
        if (!data.pids.empty()) {
            EnumWindows(GuardSpotifyWindow, reinterpret_cast<LPARAM>(&data));
        }
        Sleep(150); 
    }

    if (hParent) CloseHandle(hParent);
    return 0;
}
