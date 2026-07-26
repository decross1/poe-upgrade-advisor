# Desktop PoB capture manifest — TASK-101

This runbook produces the five independent desktop oracles required by
TASK-101. Do not use `pobcalc` to fill any expected number.

## 10-minute quickstart

1. Install Path of Building Community release **v2.66.2**. Its calculation
   source is commit `e0cc037d8b268304473454ab8b5296350f5b0d2b`
   (`Release 2.66.2 (#10010)`). The `v2.66.2` tag adds only release-manifest
   changes after that commit; it does not change calculation source.
2. Download this branch and open one `.pobcode` file from
   [`pob_capture_cases/`](pob_capture_cases/). Copy its single line into
   **Import/Export Build → Import from website/code → Import**.
3. Open **Configuration**. Keep every imported value unchanged except the
   values listed for that case below. Set every listed value explicitly.
4. Open **Calcs** without changing the imported skill selection. Record
   baseline `FullDPS` and `TotalEHP`. If `FullDPS` is absent, record which
   fallback field is present (`CombinedDPS` or `TotalDPS`) and its value.
5. Copy the case's exact candidate item block below. In **Items**, choose
   **Create custom… → Paste item**, save it, and equip it in the exact slot
   listed. Do not change gems, tree, flasks, item set, or any other config.
6. Record candidate `FullDPS` (or the same named fallback) and `TotalEHP`.
7. Fill the case template. Attach either a version screenshot or the complete
   version string, plus baseline/candidate Calcs screenshots if available.
8. Repeat for all five cases. Reply on issue #6 with the five filled templates
   and attachments; do not round, abbreviate, or add thousands separators.

For the least error-prone handoff, fill
[`results.template.json`](pob_capture_cases/results.template.json); all five
case ids, scenarios, slots, release fields, and metric fields are prefilled.

If a code will not import, stop on that case and report the case id plus the
exact PoB error. Do not repair or resave the build: that would change the
oracle input.

## Pinned configuration semantics

These are the mechanically compiled values from
`assumptions/pob_translation.yaml` translation version 1.

| Preset | Set these Path of Building configuration values |
| --- | --- |
| Mapping | `enemyIsBoss=None`; `enemyLevel=84`; `multiplierNearbyEnemies=8`; `conditionKilledRecently=true`; `buffOnslaught=false` |
| Bossing | `enemyIsBoss=Pinnacle`; `enemyLevel=85`; `multiplierNearbyEnemies=1`; `conditionKilledRecently=false` |

The desktop UI may label these controls in prose. The values above are the
canonical PoB keys and exact stored values. In particular, Mapping's nearby
enemy count is **8**, and Bossing's is **1**. Leave all unlisted imported
configuration values unchanged because the headless adapter does the same.

## Case 1 — Lightning Arrow Deadeye

- Case id: `attack-lightning-arrow-deadeye`
- Scenario: **Mapping**
- Build import code:
  [`attack-lightning-arrow-deadeye.pobcode`](pob_capture_cases/attack-lightning-arrow-deadeye.pobcode)
- Immutable source:
  [`Lightning Arrow Deadeye.xml` at 49e9f5c](https://github.com/WillsApps/random_work/blob/49e9f5c2ee5f81fc3063ad579c56e47a1b3fcaee/src/poe_builds/archived/3.26_Mercenary/Lightning%20Arrow%20Deadeye.xml)
- Decoded XML SHA-256:
  `98fd63b68e2048ae0d8430eff932183dfb709a35b3ff848f5cbf13eac8adba91`
- Imported Calcs selection: leave unchanged (`Lightning Arrow` is the
  representative skill)
- Candidate equipment slot: `Weapon 1`
- Exact candidate item:

```text
Rarity: RARE
Capture Tempest
Thicket Bow
Item Level: 85
Quality: 20
Sockets: G-G-G-G-G-G
LevelReq: 56
Implicits: 0
Adds 155 to 265 Fire Damage
Adds 135 to 235 Cold Damage
Adds 30 to 425 Lightning Damage
12% increased Attack Speed
25% increased Critical Strike Chance
+30% to Global Critical Strike Multiplier
```

## Case 2 — Forbidden Rite of Soul Sacrifice

- Case id: `spell-forbidden-rite`
- Scenario: **Bossing**
- Build import code:
  [`spell-forbidden-rite.pobcode`](pob_capture_cases/spell-forbidden-rite.pobcode)
- Immutable source:
  [`Forbidden Rite of Soul Sacrifice.xml` at 49e9f5c](https://github.com/WillsApps/random_work/blob/49e9f5c2ee5f81fc3063ad579c56e47a1b3fcaee/src/poe_builds/archived/3.26_Mercenary/Forbidden%20Rite%20of%20Soul%20Sacrifice.xml)
- Decoded XML SHA-256:
  `d36000417b93b283e32a56a4d42e15d7e58750793e16c67d96802c8f820b167c`
- Imported Calcs selection: leave unchanged (`Forbidden Rite of Soul
  Sacrifice` is the representative skill)
- Candidate equipment slot: `Weapon 1`
- Exact candidate item:

```text
Rarity: RARE
Capture Chant
Prophecy Wand
Item Level: 85
Quality: 20
Sockets: B-B-B
LevelReq: 68
Implicits: 1
40% increased Spell Damage
100% increased Spell Damage
+1 to Level of all Chaos Spell Skill Gems
90% increased Spell Critical Strike Chance
+35% to Global Critical Strike Multiplier
```

## Case 3 — Boneshatter Juggernaut

- Case id: `attack-boneshatter-jugg`
- Scenario: **Mapping**
- Build import code:
  [`attack-boneshatter-jugg.pobcode`](pob_capture_cases/attack-boneshatter-jugg.pobcode)
- Immutable source:
  [`Boneshatter Jugg.xml` at 49e9f5c](https://github.com/WillsApps/random_work/blob/49e9f5c2ee5f81fc3063ad579c56e47a1b3fcaee/src/poe_builds/archived/3.27_keepers_of_the_flame/Boneshatter%20Jugg.xml)
- Decoded XML SHA-256:
  `be5df1305393ea8ac70daa696db337321558652c50ed07450aefe8b2f9a9cb7e`
- Imported Calcs selection: leave unchanged (`Boneshatter` is the representative
  skill)
- Candidate equipment slot: `Weapon 1`
- Exact candidate item:

```text
Rarity: RARE
Capture Cleaver
Tomahawk
Item Level: 85
Quality: 20
Sockets: G-R
LevelReq: 39
Implicits: 0
180% increased Physical Damage
Adds 25 to 45 Physical Damage
20% increased Attack Speed
20% increased Critical Strike Chance
```

## Case 4 — CoC Forbidden Rite

- Case id: `trigger-coc-forbidden-rite`
- Scenario: **Bossing**
- Build import code:
  [`trigger-coc-forbidden-rite.pobcode`](pob_capture_cases/trigger-coc-forbidden-rite.pobcode)
- Immutable source:
  [`Unlimited regen shav coc forbidden rite.xml` at 49e9f5c](https://github.com/WillsApps/random_work/blob/49e9f5c2ee5f81fc3063ad579c56e47a1b3fcaee/src/poe_builds/archived/3.25.5_Legacy_of_Phrecia/Unlimited%20regen%20shav%20coc%20forbidden%20rite.xml)
- Decoded XML SHA-256:
  `5d8c203ebc0f69fba4e85da11d9a3de371a49dc2875674d59cd8a96d3bef0973`
- Imported Calcs selection: leave unchanged (`Forbidden Rite` is the
  representative skill)
- Candidate equipment slot: `Weapon 1`
- Exact candidate item:

```text
Rarity: RARE
Capture Needle
Whalebone Rapier
Item Level: 85
Quality: 20
Sockets: G-G-G
LevelReq: 58
Implicits: 1
+25% to Global Critical Strike Multiplier
40% increased Critical Strike Chance
90% increased Spell Damage
Hits can't be Evaded
```

## Case 5 — Max-resistance Doryani Mercenary

- Case id: `defense-max-res-doryani`
- Scenario: **Bossing**
- Build import code:
  [`defense-max-res-doryani.pobcode`](pob_capture_cases/defense-max-res-doryani.pobcode)
- Immutable source:
  [`Max Res Doryani Merc.xml` at 49e9f5c](https://github.com/WillsApps/random_work/blob/49e9f5c2ee5f81fc3063ad579c56e47a1b3fcaee/src/poe_builds/archived/3.26_Mercenary/Max%20Res%20Doryani%20Merc.xml)
- Decoded XML SHA-256:
  `55a5bd2c36084c4977651faa564f868b8163fd592996c6c3048732aa58f81c5c`
- Imported Calcs selection: leave unchanged (`Purity of Lightning` is the
  representative skill; an absent DPS metric is valid for this defense case)
- Candidate equipment slot: `Body Armour`
- Exact candidate item:

```text
Rarity: RARE
Capture Shell
Saint's Hauberk
Item Level: 85
Quality: 20
Sockets: R-R-R-R-R-R
LevelReq: 67
Implicits: 1
+1% to all maximum Resistances
180% increased Armour and Energy Shield
+100 to maximum Life
+40% to Lightning Resistance
```

## Fill-in template — copy once per case

```text
case_id:
scenario: mapping | bossing
desktop_release: v2.66.2
desktop_version_string:
version_screenshot_attachment:
main_skill_selected:
equipment_slot:
calculation_field_used: FullDPS | CombinedDPS | TotalDPS
baseline_calculation_value:
candidate_calculation_value:
baseline_TotalEHP:
candidate_TotalEHP:
baseline_calcs_screenshot_attachment:
candidate_calcs_screenshot_attachment:
operator_notes: none
```

Values must be copied at full precision as displayed. If PoB displays a suffix
such as `k` or `m`, use the Calcs breakdown/raw numeric value rather than the
abbreviated summary. If a required field is absent, write `ABSENT` and attach a
screenshot; do not substitute a different metric without naming it.

## Import-code provenance

The five `.pobcode` files are zlib-compressed, URL-safe-base64 encodings of
the immutable XML sources above, generated without loading or calculating the
builds. They select the exact builds already staged by TASK-102 corpus WIP
commit `70fcb5e2f2e6ef7af5d47c03346aae592756f381`. Their future captured outputs
will become TASK-101 seed fixtures; the headless wrapper is not an oracle.

## Backend replay runtime provenance

The Linux replay used to validate every candidate and slot in this manifest
was built without `sudo` under `/home/decross1/.local/pobcalc-runtime`:

- LuaJIT source commit:
  `a471ab78c7b670b4f92dae111fc3c96fb824c768`
- lua-utf8 source commit:
  `08b0fc930f5a52eff36348ed1ea39aadfc697fa6`
- Native module:
  `cc -O2 -fPIC -shared -I<luajit>/src -o <runtime>/lib/lua/5.1/lua-utf8.so lutf8lib.c`
- Engine environment:
  `POBCALC_LUA=<runtime>/bin/luajit` and
  `POBCALC_LUA_CPATH=<runtime>/lib/lua/5.1/?.so;;`

This user-local build proves no system package is required. It is not the
desktop oracle and is not yet the hermetic CI package.
