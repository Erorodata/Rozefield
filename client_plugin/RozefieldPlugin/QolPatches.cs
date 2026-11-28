using System;
using HarmonyLib;
using Inutan;

namespace RozefieldPlugin
{
    /// <summary>
    /// QOL (B3): Pre-fills the player's existing Status/Bio (signature) text when opening
    /// the signature editor so the player can edit it instead of rewriting from scratch.
    /// </summary>
    [HarmonyPatch]
    internal static class ProfileSignPrefillPatch
    {
        private static string _currentSign = string.Empty;

        [HarmonyPostfix]
        [HarmonyPatch(typeof(UI_Player_ViewCtrl), nameof(UI_Player_ViewCtrl.Set_Signature_Text))]
        private static void CaptureSignature(string str)
        {
            if (str != null)
                _currentSign = str;
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(UI_Player_ViewCtrl), nameof(UI_Player_ViewCtrl.Set_SignatureChange_Active))]
        private static void PrefillSignatureInput(UI_Player_ViewCtrl __instance, bool isActive)
        {
            if (!isActive || __instance == null || string.IsNullOrEmpty(_currentSign)) return;
            try
            {
                // Pre-fill whichever TMP_InputField is active in the signature edit modal
                var f1 = __instance.field_Public_TMP_InputField_1;
                if (f1 != null && f1.gameObject.activeInHierarchy)
                {
                    if (string.IsNullOrEmpty(f1.text))
                        f1.text = _currentSign;
                    return;
                }
                var f0 = __instance.field_Public_TMP_InputField_0;
                if (f0 != null && f0.gameObject.activeInHierarchy)
                {
                    if (string.IsNullOrEmpty(f0.text))
                        f0.text = _currentSign;
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[ProfileSignPrefill] error: {e.Message}");
            }
        }
    }

    /// <summary>
    /// QOL (B4): Locks World Map transfer / Rota Plaza warp UI while the player is still
    /// below Captain Level 2 (in the tutorial stage).
    /// </summary>
    [HarmonyPatch]
    internal static class TutorialMapLockPatch
    {
        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIMenuMapSystem), nameof(UIMenuMapSystem.Set_MapPage_Transfer_isShow))]
        private static void HideTransferBeforeLv2(ref bool isShow)
        {
            if (ChatLevelGatePatch.CaptainLevel < 2)
                isShow = false;
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIMenuMapSystem), nameof(UIMenuMapSystem.OnShowDeliveryList))]
        private static bool BlockDeliveryBeforeLv2()
        {
            return ChatLevelGatePatch.CaptainLevel >= 2;
        }
    }
}
