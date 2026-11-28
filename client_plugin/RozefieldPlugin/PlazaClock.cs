using System;
using Il2CppInterop.Runtime.Injection;
using Inutan;
using UnityEngine;

namespace RozefieldPlugin
{
    /// <summary>
    /// QOL (B5): Compact HUD clock showing OverField's own in-game Day/Night TOD clock
    /// (read directly from static Inutan.ITimeOfDaySystem.GetTimeLine()). Toggleable with F9.
    /// </summary>
    internal static class PlazaClockManager
    {
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
            if (!PlazaClockManager.ShowClock) return;

            float tl;
            try
            {
                var tod = ITimeOfDaySystem.TimeOfDaySystem;
                if (tod == null) return;
                tl = ITimeOfDaySystem.GetTimeLine();
            }
            catch
            {
                return;
            }

            if (float.IsNaN(tl) || float.IsInfinity(tl)) return;

            // OverField TOD timeline is 0..24 hours (fallback to 0..1 normalized if <= 1)
            float hours = (tl >= 0f && tl <= 1.0001f) ? tl * 24f : (tl % 24f + 24f) % 24f;
            int hh = (int)hours;
            int mm = (int)((hours - hh) * 60f);
            string phase = (hh >= 6 && hh < 18) ? "Day" : "Night";
            string label = $"{phase}  {hh:00}:{mm:00}";

            // Placed top-center-left so it never overlaps the avatar portrait or quest tracker
            GUI.Box(new Rect(110, 14, 128, 28), label);
        }
    }
}
