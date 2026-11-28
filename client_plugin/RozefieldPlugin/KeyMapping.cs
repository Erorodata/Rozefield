using System;
using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.EventSystems;

namespace RozefieldPlugin
{
    internal sealed class KeyBindEntry
    {
        public string Label;
        public KeyCode DefaultKey;
        public ConfigEntry<KeyCode> Config;
    }

    /// <summary>
    /// QOL: Customizable keyboard button mapping accessible from Game Settings (or F8 anytime).
    /// Persists bindings in BepInEx\config\com.rozefield.plugin.cfg and auto-pauses while typing
    /// in any text input field.
    /// </summary>
    internal static class KeyMappingManager
    {
        internal static readonly List<KeyBindEntry> Entries = new();
        internal static readonly Dictionary<KeyCode, KeyCode> Remap = new();
        internal static bool ShowWindow;
        internal static int RebindingIndex = -1;
        internal static UI_Setting_ViewCtrl ActiveSettingCtrl;
        internal static bool BypassInputHook;

        private static readonly (string key, string label, KeyCode def)[] Defaults =
        {
            ("Interact",  "Interact",     KeyCode.F),
            ("Skill1",    "Skill 1",      KeyCode.Q),
            ("Skill2",    "Skill 2",      KeyCode.E),
            ("Ultimate",  "Ultimate",     KeyCode.R),
            ("Dodge",     "Dodge / Dash", KeyCode.LeftShift),
            ("Jump",      "Jump",         KeyCode.Space),
            ("Chat",      "Open Chat",    KeyCode.Return),
            ("Bag",       "Bag",          KeyCode.B),
            ("Map",       "Map",          KeyCode.M),
            ("Quest",     "Quest",        KeyCode.J),
            ("Cursor",    "Show Cursor",  KeyCode.LeftAlt),
            ("MoveUp",    "Move Forward", KeyCode.W),
            ("MoveDown",  "Move Back",    KeyCode.S),
            ("MoveLeft",  "Move Left",    KeyCode.A),
            ("MoveRight", "Move Right",   KeyCode.D),
        };

        internal static void Init(ConfigFile cfg)
        {
            Entries.Clear();
            foreach (var (k, label, def) in Defaults)
            {
                var entry = cfg.Bind("KeyMapping", k, def, $"Custom keybind for {label} (default: {def})");
                Entries.Add(new KeyBindEntry { Label = label, DefaultKey = def, Config = entry });
            }
            RebuildMap();
            ClassInjector.RegisterTypeInIl2Cpp<KeyMappingOverlay>();
            var go = new GameObject("RozefieldKeyMappingUI");
            UnityEngine.Object.DontDestroyOnLoad(go);
            go.hideFlags = HideFlags.HideAndDontSave;
            go.AddComponent<KeyMappingOverlay>();
        }

        internal static void RebuildMap()
        {
            Remap.Clear();
            foreach (var e in Entries)
            {
                if (e.Config.Value != e.DefaultKey && e.Config.Value != KeyCode.None)
                    Remap[e.DefaultKey] = e.Config.Value;
            }
        }

        internal static void ResetDefaults()
        {
            foreach (var e in Entries)
                e.Config.Value = e.DefaultKey;
            RebuildMap();
        }

        internal static bool IsTypingInField()
        {
            try
            {
                var es = EventSystem.current;
                if (es == null) return false;
                var sel = es.currentSelectedGameObject;
                if (sel == null) return false;
                var n = sel.name;
                return n != null && (n.Contains("Input", StringComparison.OrdinalIgnoreCase) || n.Contains("Chat", StringComparison.OrdinalIgnoreCase));
            }
            catch { return false; }
        }

        internal static bool SettingsOpen()
        {
            try { return ActiveSettingCtrl != null && ActiveSettingCtrl.gameObject != null && ActiveSettingCtrl.gameObject.activeInHierarchy; }
            catch { return false; }
        }
    }

    internal class KeyMappingOverlay : MonoBehaviour
    {
        public KeyMappingOverlay(IntPtr ptr) : base(ptr) { }

        private Vector2 _scroll;
        private Rect _winRect = new(140, 90, 420, 520);

        private void Update()
        {
            KeyMappingManager.BypassInputHook = true;
            try
            {
                if (Input.GetKeyDown(KeyCode.F8))
                {
                    KeyMappingManager.ShowWindow = !KeyMappingManager.ShowWindow;
                    KeyMappingManager.RebindingIndex = -1;
                }
                if (KeyMappingManager.ShowWindow && KeyMappingManager.RebindingIndex >= 0)
                {
                    if (Input.GetKeyDown(KeyCode.Escape))
                    {
                        KeyMappingManager.RebindingIndex = -1;
                    }
                    else
                    {
                        foreach (KeyCode kc in Enum.GetValues(typeof(KeyCode)))
                        {
                            if (kc == KeyCode.None || kc == KeyCode.Mouse0 || kc == KeyCode.Mouse1 || kc == KeyCode.F8)
                                continue;
                            if (Input.GetKeyDown(kc))
                            {
                                var e = KeyMappingManager.Entries[KeyMappingManager.RebindingIndex];
                                e.Config.Value = kc;
                                KeyMappingManager.RebuildMap();
                                KeyMappingManager.RebindingIndex = -1;
                                Plugin.Log.LogInfo($"[KeyMapping] {e.Label} -> {kc}");
                                break;
                            }
                        }
                    }
                }
            }
            finally
            {
                KeyMappingManager.BypassInputHook = false;
            }
        }

        private void OnGUI()
        {
            // Show a clean "Key Mapping (F8)" button at top-right whenever Game Settings is open
            if (KeyMappingManager.SettingsOpen() && !KeyMappingManager.ShowWindow)
            {
                if (GUI.Button(new Rect(Screen.width - 210, 18, 150, 34), "Key Mapping (F8)"))
                {
                    KeyMappingManager.ShowWindow = true;
                    KeyMappingManager.RebindingIndex = -1;
                }
            }

            if (!KeyMappingManager.ShowWindow) return;

            GUI.Box(_winRect, "Rozefield — Key Mapping (F8)");
            GUILayout.BeginArea(new Rect(_winRect.x + 14, _winRect.y + 30, _winRect.width - 28, _winRect.height - 42));

            GUILayout.Label("Click any key button, then press the new key (Esc to cancel):");
            GUILayout.Space(6);

            _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.Height(_winRect.height - 125));
            for (int i = 0; i < KeyMappingManager.Entries.Count; i++)
            {
                var e = KeyMappingManager.Entries[i];
                GUILayout.BeginHorizontal();
                GUILayout.Label(e.Label, GUILayout.Width(175));
                string btnText = KeyMappingManager.RebindingIndex == i
                    ? "Press any key..."
                    : (e.Config.Value == e.DefaultKey ? $"{e.Config.Value}" : $"{e.Config.Value}  (was {e.DefaultKey})");
                if (GUILayout.Button(btnText, GUILayout.Height(26)))
                    KeyMappingManager.RebindingIndex = i;
                GUILayout.EndHorizontal();
                GUILayout.Space(2);
            }
            GUILayout.EndScrollView();

            GUILayout.Space(8);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Reset Defaults", GUILayout.Height(30)))
            {
                KeyMappingManager.ResetDefaults();
                KeyMappingManager.RebindingIndex = -1;
            }
            if (GUILayout.Button("Close", GUILayout.Height(30)))
            {
                KeyMappingManager.ShowWindow = false;
                KeyMappingManager.RebindingIndex = -1;
            }
            GUILayout.EndHorizontal();

            GUILayout.EndArea();
        }
    }

    [HarmonyPatch]
    internal static class KeyMappingInputPatch
    {
        private static void Translate(ref KeyCode key)
        {
            if (KeyMappingManager.BypassInputHook || KeyMappingManager.RebindingIndex >= 0 || KeyMappingManager.Remap.Count == 0)
                return;
            if (KeyMappingManager.IsTypingInField())
                return;
            if (KeyMappingManager.Remap.TryGetValue(key, out var mapped))
                key = mapped;
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(Input), nameof(Input.GetKey), new[] { typeof(KeyCode) })]
        private static void PreGetKey(ref KeyCode key) => Translate(ref key);

        [HarmonyPrefix]
        [HarmonyPatch(typeof(Input), nameof(Input.GetKeyDown), new[] { typeof(KeyCode) })]
        private static void PreGetKeyDown(ref KeyCode key) => Translate(ref key);

        [HarmonyPrefix]
        [HarmonyPatch(typeof(Input), nameof(Input.GetKeyUp), new[] { typeof(KeyCode) })]
        private static void PreGetKeyUp(ref KeyCode key) => Translate(ref key);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(UI_Setting_ViewCtrl), nameof(UI_Setting_ViewCtrl.Init))]
        private static void PostSettingInit(UI_Setting_ViewCtrl __instance)
        {
            KeyMappingManager.ActiveSettingCtrl = __instance;
        }
    }
}
