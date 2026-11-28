using System;
using HarmonyLib;
using Inutan;
using Protocol;

namespace RozefieldPlugin
{
    /// <summary>
    /// Handles the dedicated Tools bar button ID 2009 ("Parasol Etiquette", IconID 4000)
    /// without touching Shovel (ID 2008 / NewWeaponType=22) or Bug Net (ID 2002 / NewWeaponType=7).
    ///
    /// Parasol Etiquette weapons (1070000 + umbrellaId) use dedicated NewWeaponType=23 in weapon.bytes
    /// so they never appear in Bug Net / Shovel lists. When toggled ON, we temporarily map ONLY the
    /// active parasol weapon's backing field newWeaponType_ from 23 -> 7 (Bug Net over-the-shoulder
    /// idle/walk pose) and restore it to 23 when unequipped.
    /// </summary>
    [HarmonyPatch]
    internal static class ParasolEtiquettePatch
    {
        private const int PARASOL_TOOL_EXPR_ID = 2009;
        private const int PARASOL_WEAPON_MIN = 1070000;
        private const int PARASOL_WEAPON_MAX = 1079999;
        private const int WEAPON_TYPE_BUG_NET = 7;
        private const int WEAPON_TYPE_PARASOL = 23;

        private static bool _holdingParasol;
        private static WeaponConfigure _activeCfg;
        private static int _activeWeaponId;

        private static void RestoreActiveWeaponType()
        {
            if (_activeCfg != null)
            {
                try { _activeCfg.newWeaponType_ = WEAPON_TYPE_PARASOL; } catch { }
                _activeCfg = null;
            }
            _activeWeaponId = 0;
            _holdingParasol = false;
        }

        /// <summary>
        /// Locate the player's Parasol Etiquette EquipItemModel (1070000..1079999) in bag.
        /// Picks the highest-instanceId (most recently granted/selected) parasol weapon if multiple exist.
        /// </summary>
        private static EquipItemModel FindParasolWeapon(out WeaponConfigure cfgOut, out int weaponIdOut)
        {
            cfgOut = null;
            weaponIdOut = 0;

            try
            {
                var list = IBagsSystem.GetWeaponList(false);
                if (list == null) return null;

                EquipItemModel best = null;
                int bestId = 0;

                for (int i = 0; i < list.Count; i++)
                {
                    var item = list[i];
                    if (item == null) continue;
                    int id = item.ID;
                    if (id < PARASOL_WEAPON_MIN || id > PARASOL_WEAPON_MAX) continue;

                    // Keep the latest parasol weapon entry (matches the most recently selected umbrella)
                    best = item;
                    bestId = id;
                }

                if (best != null)
                {
                    weaponIdOut = bestId;
                    cfgOut = WeaponConfigureManager.FindWeapon(bestId, false);
                }
                return best;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[ParasolEtiquette] FindParasolWeapon error: {e.Message}");
                return null;
            }
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(UIEmotionSystem), nameof(UIEmotionSystem.OnClickTools))]
        private static bool OnClickToolsPrefix(int id)
        {
            if (id != PARASOL_TOOL_EXPR_ID)
            {
                // Switching to Bare Hands (2000) or any other tool restores 23 on the parasol config
                if (_holdingParasol)
                    RestoreActiveWeaponType();
                return true;
            }

            try
            {
                if (_holdingParasol)
                {
                    // Toggle OFF -> bare hands
                    IPlayerSystem.MainCharacterChangeGatherWeapon(false, null, null);
                    RestoreActiveWeaponType();
                    Plugin.Log.LogInfo("[ParasolEtiquette] Unequipped parasol.");
                    return false;
                }

                var model = FindParasolWeapon(out var cfg, out int wid);
                if (model == null)
                {
                    Plugin.Log.LogWarning("[ParasolEtiquette] No 107xxxx parasol weapon found in bag.");
                    return false;
                }

                // Temporarily map NewWeaponType 23 -> 7 (Bug Net over-the-shoulder pose) while held
                if (cfg != null)
                {
                    cfg.newWeaponType_ = WEAPON_TYPE_BUG_NET;
                    _activeCfg = cfg;
                }
                _activeWeaponId = wid;
                _holdingParasol = true;

                IPlayerSystem.MainCharacterChangeGatherWeapon(true, model, null);
                Plugin.Log.LogInfo($"[ParasolEtiquette] Equipped parasol weapon {wid} (23->7 pose).");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"[ParasolEtiquette] OnClickTools(2009) error: {e.Message}");
                RestoreActiveWeaponType();
            }

            return false; // Handled — skip base OnClickTools switch
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(PlayerSystem), nameof(PlayerSystem.MainPlayerChangeGatherWeapon))]
        private static void OnGatherWeaponChanged(bool isEquip, EquipItemModel model)
        {
            if (!_holdingParasol) return;
            if (!isEquip || model == null || model.ID != _activeWeaponId)
                RestoreActiveWeaponType();
        }
    }
}
