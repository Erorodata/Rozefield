using System;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using Inutan;
using UnityEngine;

namespace RozefieldPlugin
{
    /// <summary>
    /// QOL (B5): Compact HUD clock showing OverField's own in-game Day/Night TOD clock
    /// (read from Inutan.TimeOfDaySystem.GetTimeLine(), 0..24h). Toggleable with F9.
    /// </summary>
    internal static class PlazaClockManager
    {
        internal static TimeOfDaySystem ActiveTod;
        internal static bool ShowClock = true;

        internal static void Init()
        {
            ClassInjector.RegisterTypeInIl2Cpp<PlazaClockOverlay>();
            var go = new GameObject("RozefieldPlazaClockUI");
            UnityEngine.Object.DontDestroyOnLoad(go);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.AddComponent<PlazaClockOverlay>();
        }
    }

    internal class PlazaClockOverlay : MonoBehaviour
    {
        public PlazaClockOverlay(IntPtr ptr) : base(ptr) { }

        private void Update()
        {
            KeyMappingManager.BypassInputHook = true;
            try
            {
                if (Input.GetKeyDown(KeyCode.F9))
                    PlazaClockManager.ShowClock = !PlazaClockManager.ShowClock;
            }
            finally
            {
                KeyMappingManager.BypassInputHook = false;
            }
        }

        private void OnGUI()
        {
            if (!PlazaClockManager.ShowClock || PlazaClockManager.ActiveTod == null) return;
            float tl;
            try { tl = PlazaClockManager.ActiveTod.GetTimeLine(); }
            catch { return; }

            // Normalize to 0..24 hours (some scenes use 0..1 normalized, others 0..24)
            float hours = (tl >= 0f && tl <= 1.0001f) ? tl * 24f : (tl % 24f + 24f) % 24f;
            int hh = (int)hours;
            int mm = (int)((hours - hh) * 60f);
            string phase = (hh >= 6 && hh < 18) ? "Day" : "Night";
            string label = $"{phase}  {hh:00}:{mm:00}";

            GUI.Box(new Rect(14, 14, 128, 28), label);
        }
    }

    [HarmonyPatch]
    internal static class PlazaClockPatch
    {
        [HarmonyPostfix]
        [HarmonyPatch(typeof(TimeOfDaySystem), nameof(TimeOfDaySystem.GetTimeLine))]
        private static void CaptureTod(TimeOfDaySystem __instance)
        {
            if (__instance != null)
                PlazaClockManager.ActiveTod = __instance;
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TimeOfDaySystem), nameof(TimeOfDaySystem.SetTimeLineByServer))]
        private static void CaptureTodServer(TimeOfDaySystem __instance)
        {
            if (__instance != null)
                PlazaClockManager.ActiveTod = __instance;
        }
    }
}
