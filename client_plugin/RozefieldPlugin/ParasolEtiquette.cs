using System;
using HarmonyLib;
using Inutan;
using Protocol;
using UnityEngine;
using YooAsset;

namespace RozefieldPlugin
{
    /// <summary>
    /// Handles the dedicated Tools bar button ID 2009 ("Parasol Etiquette", UIExpressionIcon 2009)
    /// without touching Shovel (ID 2008 / NewWeaponType=22) or Bug Net (ID 2002 / NewWeaponType=7).
    ///
    /// Zero hooks on UnitWeaponSystem during login/scene-load: only activates when the player
    /// clicks Parasol Etiquette (ID 2009).
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
        private static bool _attachAttempted;
        private static WeaponConfigure _activeCfg;
        private static int _activeWeaponId;
        private static GameObject _spawnedUmbrella;
        private static AssetHandle _umbrellaHandle;

        private static void CleanupUmbrellaMesh()
        {
            _attachAttempted = false;
            if (_spawnedUmbrella != null)
            {
                try { UnityEngine.Object.Destroy(_spawnedUmbrella); } catch { }
                _spawnedUmbrella = null;
            }
            if (_umbrellaHandle != null)
            {
                try { _umbrellaHandle.Release(); } catch { }
                _umbrellaHandle = null;
            }
        }

        private static void RestoreActiveWeaponType()
        {
            CleanupUmbrellaMesh();
            if (_activeCfg != null)
            {
                try { _activeCfg.newWeaponType_ = WEAPON_TYPE_PARASOL; } catch { }
                _activeCfg = null;
            }
            _activeWeaponId = 0;
            _holdingParasol = false;
        }

        private static void TryAttachUmbrellaToMainPlayer(int weaponId)
        {
            if (weaponId < PARASOL_WEAPON_MIN) return;
            int umbrellaId = weaponId - PARASOL_WEAPON_MIN;
            if (umbrellaId <= 0) return;

            try
            {
                var ucfg = UmbrellaConfigureManager.FindUmbrella(umbrellaId, false);
                string assetPath = ucfg?.AssetFullName;
                if (string.IsNullOrEmpty(assetPath)) return;

                // Find active WeaponController on the main character's Bug Net host
                var allWcs = UnityEngine.Object.FindObjectsOfType<WeaponController>();
                if (allWcs == null || allWcs.Length == 0) return;

                WeaponController targetWc = null;
                for (int i = 0; i < allWcs.Length; i++)
                {
                    var wc = allWcs[i];
                    if (wc != null && wc.gameObject.activeInHierarchy && wc.gameObject.name.Contains("InsectNet", StringComparison.OrdinalIgnoreCase))
                    {
                        targetWc = wc;
                        break;
                    }
                }
                if (targetWc == null) return;

                CleanupUmbrellaMesh();
                _attachAttempted = true;

                try { targetWc.HideModel(); } catch { }
                var renderers = targetWc.GetComponentsInChildren<Renderer>(true);
                if (renderers != null)
                {
                    for (int i = 0; i < renderers.Length; i++)
                    {
                        if (renderers[i] != null) renderers[i].enabled = false;
                    }
                }

                string yooPath = assetPath.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase)
                    ? assetPath
                    : $"Assets/ResBundle/{assetPath}.prefab";
                var handle = YooAssets.LoadAssetSync(yooPath);
                if (handle == null || handle.AssetObject == null)
                {
                    Plugin.Log.LogWarning($"[ParasolEtiquette] YooAssets.LoadAssetSync failed for '{yooPath}'.");
                    return;
                }

                var prefab = handle.AssetObject.TryCast<GameObject>();
                if (prefab == null)
                {
                    handle.Release();
                    return;
                }

                _umbrellaHandle = handle;
                _spawnedUmbrella = UnityEngine.Object.Instantiate(prefab, targetWc.transform);
                _spawnedUmbrella.transform.localPosition = Vector3.zero;
                _spawnedUmbrella.transform.localRotation = Quaternion.identity;
                _spawnedUmbrella.transform.localScale = Vector3.one;
                _spawnedUmbrella.SetActive(true);
                Plugin.Log.LogInfo($"[ParasolEtiquette] Attached umbrella mesh '{yooPath}' onto {targetWc.gameObject.name}.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"[ParasolEtiquette] TryAttachUmbrellaToMainPlayer error: {e.Message}");
            }
        }

        internal static void Tick()
        {
            if (_holdingParasol && !_attachAttempted && _spawnedUmbrella == null && _activeWeaponId >= PARASOL_WEAPON_MIN)
            {
                TryAttachUmbrellaToMainPlayer(_activeWeaponId);
            }
        }

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
                if (_holdingParasol)
                    RestoreActiveWeaponType();
                return true;
            }

            try
            {
                if (_holdingParasol)
                {
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

            return false;
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
