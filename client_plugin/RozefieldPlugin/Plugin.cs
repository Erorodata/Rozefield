using System;
using System.Collections.Generic;
using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Inutan;
using Protocol;

namespace RozefieldPlugin
{
    [BepInPlugin("com.rozefield.plugin", "Rozefield Gameplay Plugin", "0.7.1")]
    public class Plugin : BasePlugin
    {
        internal static new ManualLogSource Log;
        private Harmony _harmony;

        private void SafePatch(Type t)
        {
            try { _harmony.PatchAll(t); }
            catch (Exception e) { Log.LogError($"PatchAll({t.Name}) failed: {e.Message}"); }
        }

        public override void Load()
        {
            Log = base.Log;
            KeyMappingManager.Init(Config);
            _harmony = new Harmony("com.rozefield.plugin");
            SafePatch(typeof(FashionChairVehiclePatch));
            SafePatch(typeof(Es3IsolationPatch));
            SafePatch(typeof(ChatLevelGatePatch));
            SafePatch(typeof(KeyMappingInputPatch));
            Log.LogInfo("RozefieldPlugin 0.7.1 loaded: Friendship's Weight + Vehicle, ES3 isolation, Lv2 Chat gate & Key Mapping active.");
        }
    }

    /// <summary>
    /// Allows Friendship's Weight (IsCanSit=1 fashion chair pendant, item 4645001) to coexist
    /// with Vehicles without modifying normal chair or vehicle physics:
    ///   - IL2CPP inlines FashionInfoConfigure.get_IsCanSit(), so instead of patching the getter,
    ///     we temporarily zero the backing field (isCanSit_) in FashionConfigureManager.FashionInfo
    ///     during UIEmotionSystem.OnClickTools, UIFashionSystem.OnSelectItem/OnSelectItemButtonClick,
    ///     and PlayerSystem.MainPlayerChangeGatherWeapon, then restore it in the Finalizer.
    ///   - Keeps ChairSystem.SetFashionChairInteraction and CharacterEntity.SetFashionCharis enabled.
    /// </summary>
    [HarmonyPatch]
    internal static class FashionChairVehiclePatch
    {
        private static int _bypassDepth;
        private static readonly List<(FashionInfoConfigure cfg, int orig)> _saved = new();
        private static bool _loggedFlip;
        private static bool _loggedChair;
        private static bool _loggedCharis;

        private static void EnterBypass()
        {
            _bypassDepth++;
            if (_bypassDepth != 1) return;
            _saved.Clear();
            try
            {
                var arr = FashionConfigureManager.FashionInfo;
                if (arr == null) return;
                for (int i = 0; i < arr.Length; i++)
                {
                    var cfg = arr[i];
                    if (cfg != null && cfg.isCanSit_ != 0)
                    {
                        _saved.Add((cfg, cfg.isCanSit_));
                        cfg.isCanSit_ = 0;
                    }
                }
                if (!_loggedFlip && _saved.Count > 0)
                {
                    _loggedFlip = true;
                    Plugin.Log.LogInfo($"Temporarily bypassed isCanSit_ on {_saved.Count} sittable fashion(s) during Vehicle/Fashion click.");
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"EnterBypass error: {e.Message}");
            }
        }

        private static void ExitBypass()
        {
            if (_bypassDepth <= 0) return;
            _bypassDepth--;
            if (_bypassDepth != 0) return;
            for (int i = 0; i < _saved.Count; i++)
            {
                try { _saved[i].cfg.isCanSit_ = _saved[i].orig; } catch { }
            }
            _saved.Clear();
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIEmotionSystem), nameof(UIEmotionSystem.OnClickTools))]
        private static void PreClickTools() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIEmotionSystem), nameof(UIEmotionSystem.OnClickTools))]
        private static void PostClickTools() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItem))]
        private static void PreSelectItem() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItem))]
        private static void PostSelectItem() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClick))]
        private static void PreSelectItemBtn() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClick))]
        private static void PostSelectItemBtn() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClickNext))]
        private static void PreSelectItemBtnNext() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.OnSelectItemButtonClickNext))]
        private static void PostSelectItemBtnNext() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.TrySaveFashionSuit))]
        private static void PreTrySaveSuit() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.TrySaveFashionSuit))]
        private static void PostTrySaveSuit() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.SaveFashionSuit))]
        private static void PreSaveSuit() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.SaveFashionSuit))]
        private static void PostSaveSuit() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.FashionSuitSwitch))]
        private static void PreSuitSwitch() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(UIFashionSystem), nameof(UIFashionSystem.FashionSuitSwitch))]
        private static void PostSuitSwitch() => ExitBypass();

        [HarmonyPrefix]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.MainPlayerChangeGatherWeapon))]
        private static void PreChangeGatherWeapon() => EnterBypass();

        [HarmonyFinalizer]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.MainPlayerChangeGatherWeapon))]
        private static void PostChangeGatherWeapon() => ExitBypass();

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

    /// <summary>
    /// Hides the HUD Chat button until the player reaches Captain Level 2 (unlocked upon
    /// leaving the tutorial stage) and shows it automatically as soon as Level 2 is reached.
    /// </summary>
    [HarmonyPatch]
    internal static class ChatLevelGatePatch
    {
        private static int _captainLevel = 1;
        private static UI_Main_ViewCtrl _mainCtrl;
        private static bool _updating;

        private static void SyncChatVisibility()
        {
            if (_updating || _mainCtrl == null) return;
            try
            {
                _updating = true;
                _mainCtrl.Set_Chat_Active(_captainLevel >= 2);
            }
            catch { }
            finally { _updating = false; }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.OnPlayerLevelExpCallback))]
        private static void OnLevelExpNotice(Pb.PlayerLevelExpNotice notice)
        {
            if (notice != null && notice.Level > 0)
            {
                _captainLevel = (int)notice.Level;
                SyncChatVisibility();
            }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(PlayerModel), nameof(PlayerModel.CheckUnlockWorldLevel))]
        private static void OnModelCheck(PlayerModel __instance)
        {
            if (__instance != null && __instance.Level > 0)
            {
                _captainLevel = __instance.Level;
                SyncChatVisibility();
            }
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UI_Main_ViewCtrl), nameof(UI_Main_ViewCtrl.Set_Chat_Active))]
        private static void GateSetChatActive(UI_Main_ViewCtrl __instance, ref bool isActive)
        {
            _mainCtrl = __instance;
            if (_captainLevel < 2)
                isActive = false;
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(UI_Main_ViewCtrl), nameof(UI_Main_ViewCtrl.Set_Chat_Button))]
        private static void PostSetChatButton(UI_Main_ViewCtrl __instance)
        {
            _mainCtrl = __instance;
            if (_captainLevel < 2)
                SyncChatVisibility();
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIMainSystem), nameof(UIMainSystem.OnChatButtonClick))]
        private static bool GateChatClick() => _captainLevel >= 2;

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIMainSystem), nameof(UIMainSystem.ShowChatView))]
        private static bool GateShowChatView() => _captainLevel >= 2;

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIChatSystem), nameof(UIChatSystem.Open))]
        private static bool GateChatSystemOpen() => _captainLevel >= 2;
    }
}
