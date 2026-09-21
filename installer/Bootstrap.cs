using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;

internal static class Bootstrap {
    static string Quote(string value) {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { result.Append('\\', slashes * 2 + 1); result.Append(c); slashes = 0; continue; }
            result.Append('\\', slashes); slashes = 0; result.Append(c);
        }
        result.Append('\\', slashes * 2); return result.Append('"').ToString();
    }
    static int Main(string[] args) {
        bool unattended = false;
        try {
            string extract = null; var forwarded = new StringBuilder();
            for (int i = 0; i < args.Length; i++) {
                switch (args[i]) {
                    case "--extract-only": extract = Path.GetFullPath(args[++i]); unattended = true; break;
                    case "--root": forwarded.Append(" -InstallRoot ").Append(Quote(args[++i])); break;
                    case "--cache": forwarded.Append(" -CacheDirectory ").Append(Quote(args[++i])); break;
                    case "--target":
                        string target = args[++i].ToLowerInvariant();
                        if (target != "codex" && target != "continue") throw new ArgumentException("Cible attendue : codex ou continue.");
                        forwarded.Append(" -Target ").Append(Quote(target)); break;
                    case "--skip-desktop": forwarded.Append(" -SkipDesktop"); break;
                    case "--no-launch": forwarded.Append(" -NoLaunch"); unattended = true; break;
                    case "--no-shortcuts": forwarded.Append(" -NoShortcuts"); break;
                    default: throw new ArgumentException("Option inconnue : " + args[i]);
                }
            }
            Console.Title = "Installation ChatGPT Web2API - Codex ou Continue";
            Console.WriteLine("Preparation de l'installateur 0.4.4 - verification de l'archive embarquee...");
            string folder = extract ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Web2API-Continue-Setup", "0.4.4-" + Guid.NewGuid().ToString("N"));
            if (Directory.Exists(folder)) throw new IOException("Le dossier d'extraction existe deja : " + folder);
            Directory.CreateDirectory(folder);
            using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) {
                using (SHA256 hash = SHA256.Create()) {
                    string actual = BitConverter.ToString(hash.ComputeHash(payload)).Replace("-", "").ToLowerInvariant();
                    if (actual != "__PAYLOAD_SHA256__") throw new IOException("Integrite du programme d'installation invalide.");
                }
                payload.Position = 0;
                Console.WriteLine("Integrite SHA256 valide. Extraction des fichiers de l'installateur...");
                using (var archive = new ZipArchive(payload, ZipArchiveMode.Read)) {
                    int completed = 0;
                    var timer = Stopwatch.StartNew();
                    double lastUpdate = 0;
                    foreach (var entry in archive.Entries) {
                        string path = Path.GetFullPath(Path.Combine(folder, entry.FullName));
                        if (!path.StartsWith(folder.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("Chemin d'archive invalide.");
                        if (entry.Name.Length == 0) { Directory.CreateDirectory(path); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(path)); entry.ExtractToFile(path);
                        completed++;
                        if (timer.Elapsed.TotalSeconds - lastUpdate >= 1 || completed == archive.Entries.Count) {
                            Console.WriteLine("Extraction de l'installateur : {0}/{1} fichiers ({2:F0}%)", completed, archive.Entries.Count, 100.0 * completed / archive.Entries.Count);
                            lastUpdate = timer.Elapsed.TotalSeconds;
                        }
                    }
                }
            }
            if (extract != null) { Console.WriteLine("Archive verifiee et extraite : " + folder); return 0; }
            Console.Title = "Installation ChatGPT Web2API - Codex ou Continue";
            Console.WriteLine("Installation complete pour Windows x64. Connexion Internet requise.");
            string shell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            var start = new ProcessStartInfo(shell, "-NoProfile -ExecutionPolicy Bypass -File " + Quote(Path.Combine(folder, "installer", "Setup.ps1")) + forwarded) { UseShellExecute = false, WorkingDirectory = folder };
            // A launch from PowerShell 7 must not load its incompatible modules in 5.1.
            start.EnvironmentVariables.Remove("PSModulePath");
            using (var process = Process.Start(start)) {
                process.WaitForExit(); int code = process.ExitCode;
                if (code != 0) Console.WriteLine("Installation interrompue. Le journal indique le composant a reparer.");
                else Console.WriteLine("Installation terminee. Connectez votre propre compte dans le navigateur ChatGPT.");
                if (!unattended) { Console.WriteLine("Appuyez sur Entree pour fermer."); Console.ReadLine(); }
                return code;
            }
        } catch (Exception ex) {
            Console.Error.WriteLine(ex.Message);
            if (!unattended) { Console.WriteLine("Appuyez sur Entree pour fermer."); Console.ReadLine(); }
            return 1;
        }
    }
}
