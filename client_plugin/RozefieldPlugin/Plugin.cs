using System;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Inutan;
using Protocol;

namespace RozefieldPlugin
{
    [BepInPlugin("com.rozefield.plugin", "Rozefield Gameplay Plugin", "0.4.0")]
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
            Log.LogInfo("RozefieldPlugin 0.4.0 loaded: Friendship's Weight + Vehicle & ES3 save isolation active.");
        }
    }

    /// <summary>
    /// Allows Friendship's Weight (IsCanSit=1 fashion chair pendant, item 4645001) to coexist
    /// with Vehicles without modifying normal chair or vehicle physics:
    ///   - Temporarily returns IsCanSit=0 only during UIEmotionSystem.OnClickTools (summoning a Vehicle)
    ///     and UIFashionSystem.OnSelectItem / OnSelectItemButtonClick (equipping Friendship's Weight on a Vehicle).
    ///   - Keeps ChairSystem.SetFashionChairInteraction and CharacterEntity.SetFashionCharis enabled.
    /// </summary>
    [HarmonyPatch]
    internal static class FashionChairVehiclePatch
    {
        private static int _bypassDepth;
        private static bool _loggedBypass;
        private static bool _loggedChair;
        private static bool _loggedCharis;

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIEmotionSystem), nameof(UIEmotionSystem.OnClickTools))]
        private static void PreClickTools(int id) => _bypassDepth++;

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIEmotionSystem), nameof(UIEmotionSystem.OnClickTools))]
        private static void PostClickTools() { if (_bypassDepth > 0) _bypassDepth--; }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItem))]
        private static void PreSelectItem() => _bypassDepth++;

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItem))]
        private static void PostSelectItem() { if (_bypassDepth > 0) _bypassDepth--; }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClick))]
        private static void PreSelectItemBtn() => _bypassDepth++;

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClick))]
        private static void PostSelectItemBtn() { if (_bypassDepth > 0) _bypassDepth--; }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.MainPlayerChangeGatherWeapon))]
        private static void PreChangeGatherWeapon() => _bypassDepth++;

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.MainPlayerChangeGatherWeapon))]
        private static void PostChangeGatherWeapon() { if (_bypassDepth > 0) _bypassDepth--; }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(FashionInfoConfigure), nameof(FashionInfoConfigure.IsCanSit), MethodType.Getter)]
        private static void BypassIsCanSitDuringVehicleCheck(ref int __result)
        {
            if (_bypassDepth > 0 && __result != 0)
            {
                __result = 0;
                if (!_loggedBypass)
                {
                    _loggedBypass = true;
                    Plugin.Log.LogInfo("Bypassed IsCanSit check so Friendship's Weight + Vehicle can be used together.");
                }
            }
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(ChairSystem), nameof(ChairSystem.SetFashionChairInteraction))]
        private static void KeepFashionChairEnabled(ref bool enabled)
        {
            if (!enabled)
            {
                enabled = true;
                if (!_loggedChair)
                {
                    _loggedChair = true;
                    Plugin.Log.LogInfo("Kept ChairSystem.SetFashionChairInteraction enabled.");
                }
            }
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(CharacterEntity), nameof(CharacterEntity.SetFashionCharis))]
        private static void KeepCharacterFashionChairsEnabled(ref bool enable)
        {
            if (!enable)
            {
                enable = true;
                if (!_loggedCharis)
                {
                    _loggedCharis = true;
                    Plugin.Log.LogInfo("Kept CharacterEntity.SetFashionCharis enabled.");
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

        private static void RedirectStaticFields()
        {
            try
            {
                if (!string.IsNullOrEmpty(ES3System.PathFolder))
                    ES3System.PathFolder = Redirect(ES3System.PathFolder);
                if (!string.IsNullOrEmpty(ES3System.PathFolderBackup))
                    ES3System.PathFolderBackup = Redirect(ES3System.PathFolderBackup);
            }
            catch { }
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

        [HarmonyPrefix]
        [HarmonyPatch(typeof(ES3System), nameof(ES3System.DeleteES3Data), new[] { typeof(bool) })]
        private static void PreDeleteES3Data() => RedirectStaticFields();

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
