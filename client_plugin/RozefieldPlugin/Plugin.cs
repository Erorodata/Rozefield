using BepInEx;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Inutan;

namespace RozefieldPlugin
{
    [BepInPlugin("com.rozefield.plugin", "Rozefield Gameplay Plugin", "0.1.0")]
    public class Plugin : BasePlugin
    {
        internal static new ManualLogSource Log;
        private Harmony _harmony;

        public override void Load()
        {
            Log = base.Log;
            _harmony = new Harmony("com.rozefield.plugin");
            _harmony.PatchAll(typeof(FashionChairVehiclePatch));
            Log.LogInfo("RozefieldPlugin loaded: Friendship's Weight + Vehicle patch active.");
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
}
