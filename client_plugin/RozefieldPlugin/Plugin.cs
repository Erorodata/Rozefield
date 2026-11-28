using System;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Inutan;

namespace RozefieldPlugin
{
    [BepInPlugin("com.rozefield.plugin", "Rozefield Gameplay Plugin", "0.2.0")]
    public class Plugin : BasePlugin
    {
        internal static new ManualLogSource Log;
        private Harmony _harmony;

        public override void Load()
        {
            Log = base.Log;
            _harmony = new Harmony("com.rozefield.plugin");
            _harmony.PatchAll(typeof(FashionChairVehiclePatch));
            _harmony.PatchAll(typeof(Es3IsolationPatch));
            Log.LogInfo("RozefieldPlugin 0.2.0 loaded: Friendship's Weight + Vehicle & ES3 save isolation active.");
        }
    }

    /// <summary>
    /// Allows Friendship's Weight (IsCanSit=1 fashion chair pendant, item 4645001) to stay
    /// interactive even when a player is on/using a Vehicle, without modifying normal chair
    /// or vehicle physics.
    /// </summary>
    [HarmonyPatch]
    internal static class FashionChairVehiclePatch
    {
        private static bool _loggedOnce;

        [HarmonyPrefix]
        [HarmonyPatch(typeof(ChairSystem), nameof(ChairSystem.SetFashionChairInteraction))]
        private static void KeepFashionChairEnabled(ref bool enabled)
        {
            if (!enabled)
            {
                enabled = true;
                if (!_loggedOnce)
                {
                    _loggedOnce = true;
                    Plugin.Log.LogInfo("Kept Friendship's Weight fashion chair interaction enabled (bypassed vehicle/state disable).");
                }
            }
        }
    }

    /// <summary>
    /// Isolates Rozefield's ES3 local save/settings folder away from Steam OverField's
    /// AppData\LocalLow\Inutan\OverField\Save so both clients can run simultaneously
    /// without Setting.es3 file locks or startup freezes.
    /// </summary>
    [HarmonyPatch]
    internal static class Es3IsolationPatch
    {
        private static bool _loggedRedirect;

        private static string Redirect(string path)
        {
            if (string.IsNullOrEmpty(path)) return path;
            string orig = path;
            path = path.Replace("\\Inutan\\OverField\\", "\\Rozefield\\Rozefield\\", StringComparison.OrdinalIgnoreCase);
            path = path.Replace("/Inutan/OverField/", "/Rozefield/Rozefield/", StringComparison.OrdinalIgnoreCase);
            path = path.Replace("\\Inutan\\OverField", "\\Rozefield\\Rozefield", StringComparison.OrdinalIgnoreCase);
            path = path.Replace("/Inutan/OverField", "/Rozefield/Rozefield", StringComparison.OrdinalIgnoreCase);
            if (!_loggedRedirect && !string.Equals(orig, path, StringComparison.Ordinal))
            {
                _loggedRedirect = true;
                Plugin.Log.LogInfo($"Redirected ES3 save path -> {path}");
            }
            return path;
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.GetPathFolder))]
        private static void PostGetPathFolder(ref string __result) => __result = Redirect(__result);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.GetLocalPathFolder))]
        private static void PostGetLocalPathFolder(ref string __result) => __result = Redirect(__result);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.GetES3FilePath))]
        private static void PostGetES3FilePath(ref string __result) => __result = Redirect(__result);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.GetES3FilePathLocal))]
        private static void PostGetES3FilePathLocal(ref string __result) => __result = Redirect(__result);

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.DeleteES3Data), new[] { typeof(bool) })]
        private static Exception GuardDeleteES3Data(Exception __exception)
        {
            if (__exception != null)
            {
                Plugin.Log.LogWarning($"Suppressed ES3System.DeleteES3Data error so startup continues: {__exception.Message}");
                return null;
            }
            return null;
        }
    }
}
