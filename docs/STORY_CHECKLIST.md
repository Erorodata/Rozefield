# Story / quest check — all storylines

Every main story, side story and event storyline needs a pass on Rozefield. Use this file to track it.

## Known bug patterns (fixed 2026-11-25)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Talk option clicked, nothing happens; step stays 0/1 | The game reported the step by its scene resource ID (`ConditionSetGroup.ResourceID`, e.g. 1000121); the server only accepted the IDs in the condition's `Param` | `quests.reported()` accepts the resource ID |
| 2 | Dialogue plays, then starts over (loop) | At the end of the dialogue the game sends `NpcTalkReq {"id": <conditionId>}` (e.g. 11000121), the step's own ID | `quests.reported()` accepts the condition ID |
| 3 | Story screen "Claim reward": no popup, button unchanged (claimed after reopening) | Reply `quest.questId` was the story ID; the game looks it up in its quest table and fails (`QuestConfigure表中无法查找到ID为1000001的数据`) | Reply with the story's last real quest |

## How to check a step

1. Play the step on Rozefield.
2. Server panel log: what the game sent (`NpcTalkReq`, `TutorialReq`, `ClaimQuestRewardReq`, ...).
3. If the game sent nothing, or nothing happened on screen: check the game log
   `C:\Users\User\AppData\LocalLow\Rozefield\Rozefield\Player.log` for the error.
4. Compare the step with `quest.json` (`Quest`, `ConditionSetGroup`) and `achieve.json` (condition type, `Param`).

## Progress

| Storyline | Checked up to | Result |
|---|---|---|
| Prologue: Over Field — 01 New Companion | Done (talk, recruit, claim) | Patterns 1–3 found and fixed |
| Prologue: Over Field — 02 First Steps onward | — | To check |
| Other main chapters | — | To check |
| Extra Chapter: Investigator (CN) | — | To check |
| Side stories | — | To check |
| Event storylines | — | To check |
