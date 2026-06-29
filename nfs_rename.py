#!/usr/bin/env python3
r"""
AstralTale NFS 展開済みファイル リネームスクリプト

使い方:
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt --dry-run
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt --copy
"""

import struct, os, re, argparse, shutil
from pathlib import Path


def hash_char(b, seed):
    return (seed * 0x1000193 ^ b) & 0xFFFFFFFFFFFFFFFF

def calc_hash(filename, path):
    h = 0
    for b in filename.lower().encode('latin-1'): h = hash_char(b, h)
    for b in path.lower().encode('latin-1'):     h = hash_char(b, h)
    return h

def normalize(raw):
    s = raw.replace('\\', '/').lower()
    while '//' in s: s = s.replace('//', '/')
    while s.startswith('./'): s = s[2:]
    s = s.rstrip('/')
    idx = s.rfind('/')
    return (s[idx+1:], s[:idx]) if idx >= 0 else (s, '')


# ============================================================
# 既知パスリスト
# ============================================================
DATA_DB_FILES = [
    # Twin Saga data archive より (https://github.com/Eperty123/twin_saga_data_archive)
    "4PHouse.ini", "BiologyList.ini", "BoneScale.ini", "BoundInfo.ini",
    "C_Achievement.ini", "C_Activity.ini", "C_AdventureRoad.ini", "C_Ai.ini",
    "C_AutoTalent.ini", "C_Balance.ini", "C_BattlefieldAward.ini", "C_Biology.ini",
    "C_BiologyRef.ini", "C_CharColor.ini", "C_Class.ini", "C_ClassBase.ini",
    "C_Classes.ini", "C_Collect.ini", "C_CollectList.ini", "C_Collection.ini",
    "C_Combine.ini", "C_Cube.ini", "C_CutscenePlay.ini", "C_Dialogue.ini",
    "C_DropItem.ini", "C_DyeingItems.ini", "C_Enchant.ini", "C_EquipSet.ini",
    "C_ExchangeItem.ini", "C_Festival.ini", "C_Fight.ini", "C_FurnitureDisplay.ini",
    "C_GrowEquip.ini", "C_HouseRace.ini", "C_Item.ini", "C_ItemCombo.ini",
    "C_ItemMall.ini", "C_ItemMallEnchant.ini", "C_Level.ini", "C_Lottery.ini",
    "C_Mask.ini", "C_Memoirs.ini", "C_MemoirsPlus.ini", "C_MemoirsPlusValue.ini",
    "C_MemoirsTree.ini", "C_Mission.ini", "C_MissionList.ini", "C_MonsterHunter.ini",
    "C_MonsterStep.ini", "C_Node.ini", "C_PVP.ini", "C_PairQuest.ini",
    "C_Parameter.ini", "C_Partner.ini", "C_PartnerCombo.ini", "C_PartnerGrow.ini",
    "C_PartnerMemories.ini", "C_PartnerStuff.ini", "C_PartnerTalk.ini", "C_Party.ini",
    "C_Produce.ini", "C_ProduceLevel.ini", "C_Product.ini", "C_Races.ini",
    "C_RankAward.ini", "C_RecommendActivity.ini", "C_RecommendEvents.ini",
    "C_Reward.ini", "C_RideStep.ini", "C_Rogue.ini", "C_Schedule.ini",
    "C_SpcQuest.ini", "C_Spell.ini", "C_SpellFormula.ini", "C_StateDependence.ini",
    "C_Store.ini", "C_Strengthen.ini", "C_SysSetup.ini", "C_Talent.ini",
    "C_TextIndex.ini", "C_TextLimit.ini", "C_Title.ini", "C_Transport.ini",
    "C_TreasureKnowledge.ini", "C_Warrior.ini", "C_WeaponExterior.ini",
    "C_WeaponShift.ini", "C_WeaponSkill.ini", "C_Wizzard.ini",
    "Color.ini", "color.ini", "Decorate.ini", "DynEffect.ini", "dynEffect.ini",
    "Effect.ini", "effect.ini", "ElfEquip.ini", "Equip.ini", "Lic.ini",
    "MonsterList.ini", "Motion.ini", "NPCList.ini", "PartnerList.ini",
    "Weapon.ini", "RideList.ini",
]

DEFAULT_KNOWN = (
    [f"data/db/{f}" for f in DATA_DB_FILES] +
    [f"map/model/S{i:03d}/S{i:03d}.nif" for i in range(1, 600)] +
    [f"map/model/S{i:03d}/S{i:03d}.big" for i in range(1, 600)] +
    [f"biology/m{i:03d}.kfm" for i in range(1, 1000)] +
    [f"biology/texture/m{i:03d}{j:02d}.dds" for i in range(1, 500) for j in range(1, 20)] +
    [f"biology/texture/m{i:03d}{j:02d}a.dds" for i in range(1, 500) for j in range(1, 10)] +
    [f"biology/texture/m{i:03d}{j:02d}A.dds" for i in range(1, 500) for j in range(1, 10)] +
    ["idc.ini", "client.ini", "locate.ini", "locate_1.ini", "banner.ini"]
)


def guess_paths(fname):
    fl = fname.lower()
    paths = []
    if fl.endswith('.kfm'):
        paths.append("biology")
    if re.match(r'^m\d+', fl) and fl.endswith('.dds'):
        paths.append("biology/texture")
    m = re.match(r'^(s(\d{1,3}))\.(nif|big)$', fl)
    if m:
        sid = m.group(1)
        paths += [f"map/model/{sid}", "map/model"]
    m = re.match(r'^(s(\d{4,}))\.(nif|big)$', fl)
    if m:
        sid = m.group(1)
        paths += [f"map/model/{sid[:4]}", f"map/model/{sid[:5]}", "map/model"]
    if fl in {f.lower() for f in DATA_DB_FILES}:
        paths.append("data/db")
    return paths


def build_hash_map(refs, extra_paths=None):
    hmap = {}
    for raw in (extra_paths or []) + DEFAULT_KNOWN:
        fn, pt = normalize(raw)
        if fn:
            h = calc_hash(fn, pt)
            if h not in hmap:
                hmap[h] = raw
    for fname in refs:
        for path in guess_paths(fname):
            fn, pt = normalize(f"{path}/{fname}")
            h = calc_hash(fn, pt)
            if h not in hmap:
                hmap[h] = f"{path}/{fname}"
    return hmap


def main():
    parser = argparse.ArgumentParser(description="AstralTale 展開済みファイル リネームツール")
    parser.add_argument("--out",     required=True)
    parser.add_argument("--refs",    default=None,  help="refs.txt（iniから抽出したファイル名リスト）")
    parser.add_argument("--paths",   default=None,  help="フルパス形式の追加パスリスト")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--copy",    action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[ERROR] フォルダが見つかりません: {out_dir}"); return

    refs = []
    if args.refs:
        with open(args.refs, 'r', encoding='utf-8-sig') as f:
            refs = [l.strip() for l in f if l.strip()]
        print(f"[INFO] refs.txt: {len(refs):,} 件")

    extra = []
    if args.paths:
        with open(args.paths, 'r', encoding='utf-8') as f:
            extra = [l.strip() for l in f if l.strip()]

    print("[INFO] ハッシュマップ構築中...")
    hmap = build_hash_map(refs, extra)
    print(f"[INFO] {len(hmap):,} パターン生成")

    exts = ['*.dds','*.nif','*.ini','*.txt','*.bin','*.kf','*.kfm',
            '*.smp','*.pmap','*.png','*.bmp','*.jpg','*.xml']
    files = []
    for ext in exts:
        files += list(out_dir.glob(ext))
    print(f"[INFO] 対象ファイル: {len(files):,} 件")
    print("-" * 60)

    renamed = skipped = 0
    for f in sorted(files):
        stem = f.stem
        try:
            h = int(stem, 16)
        except ValueError:
            skipped += 1; continue

        if h not in hmap:
            if args.verbose: print(f"  [UNKN] {f.name}")
            skipped += 1; continue

        known_raw = hmap[h]
        fn, pt = normalize(known_raw)
        orig_ext = f.suffix.lower()
        known_base = fn.rsplit('.', 1)[0] if '.' in fn else fn
        final_name = known_base + orig_ext

        new_dir  = out_dir / pt.replace('/', os.sep) if pt else out_dir
        new_path = new_dir / final_name

        if args.dry_run:
            print(f"  [DRY] {f.name} → {pt+'/' if pt else ''}{final_name}")
            renamed += 1; continue

        new_dir.mkdir(parents=True, exist_ok=True)
        if new_path.exists():
            if args.verbose: print(f"  [SKIP] {final_name} (既に存在)")
            skipped += 1; continue

        if args.copy: shutil.copy2(f, new_path)
        else: f.rename(new_path)

        renamed += 1
        if args.verbose or renamed % 200 == 0:
            print(f"  [{renamed:>5}] {f.name} → {pt+'/' if pt else ''}{final_name}")

    print("-" * 60)
    action = "DRY RUN" if args.dry_run else ("コピー" if args.copy else "リネーム")
    print(f"[完了] {action}: {renamed:,} 件  スキップ: {skipped:,} 件")

if __name__ == "__main__":
    main()
