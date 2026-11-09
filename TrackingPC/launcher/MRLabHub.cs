// MRLab Hub launcher (MRLabHub.exe): starts the hub (the Python package hub\) with the portable Python in
// runtime\, after pointing home, AppData and temp of the hub and of everything it starts (Ollama, the
// NVIDIA driver's caches) into runtime\, so nothing is written outside this folder (README D63).
// Build: launcher\build.bat (uses the C# compiler that is part of Windows' .NET Framework 4).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static void Main(string[] args)
    {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        string runtime = Path.Combine(folder, "runtime");
        string python = Path.Combine(runtime, @"python\pythonw.exe");
        if (!File.Exists(python))
        {
            MessageBox.Show("The runtime folder is missing.\n\nCopy the folder \"runtime\" from the USB stick into\n" + folder,
                "MRLab Hub", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        string home = Path.Combine(runtime, "home");
        string roaming = Path.Combine(home, @"AppData\Roaming");
        string local = Path.Combine(home, @"AppData\Local");
        string temp = Path.Combine(runtime, "temp");
        foreach (string dir in new[] { roaming, local, temp })
            Directory.CreateDirectory(dir);

        var start = new ProcessStartInfo(python, "-m hub " + string.Join(" ", args));
        start.UseShellExecute = false;
        start.WorkingDirectory = folder;
        var env = start.EnvironmentVariables;
        env["USERPROFILE"] = home;
        env["HOME"] = home;
        env["APPDATA"] = roaming;
        env["LOCALAPPDATA"] = local;
        env["TEMP"] = temp;
        env["TMP"] = temp;
        env["OLLAMA_MODELS"] = Path.Combine(runtime, "models");
        env["OLLAMA_HOST"] = "127.0.0.1:11435"; // its own port, so an Ollama installed on the PC is not touched
        env["PYTHONDONTWRITEBYTECODE"] = "1";
        env["PYTHONNOUSERSITE"] = "1";
        Process.Start(start);
    }
}
