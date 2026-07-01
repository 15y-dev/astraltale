#!/usr/bin/env python3
r"""
AstralTale / Twin Saga NFS 展開済みファイル リネームスクリプト

使い方:
    # 確認のみ（何も変更しない）
    python nfs_rename.py --out D:\work\astraltale\out --dry-run

    # refs.txt（iniから抽出したファイル名リスト）を追加
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt --dry-run

    # コピーモードで実行（元ファイルを残す・推奨）
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt --copy

    # リネームモードで実行（元ファイルを移動）
    python nfs_rename.py --out D:\work\astraltale\out --refs D:\work\astraltale\refs.txt
"""

import os
import re
import argparse
import shutil
from pathlib import Path

from nfs_common import calc_hash, normalize


# ============================================================
# 既知パスリスト
# ============================================================

# data/db 以下のiniファイル（Twin Saga data archive より）
_DATA_DB = [
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
    # game.binから判明
    "idc.ini", "client.ini", "locate.ini", "locate_1.ini", "banner.ini",
]

# t_*_jp.ini 翻訳データファイル（c_* から自動生成）
_TRANSLATE_JP = []
for _f in _DATA_DB:
    if _f.startswith("C_"):
        _stem = _f[2:].rsplit(".", 1)[0]  # C_Node.ini → Node
        _TRANSLATE_JP.append(f"T_{_stem}_jp.ini")

_STATIC_PATHS = (
    [f"data/db/{f}" for f in _DATA_DB] +
    [f"data/db/{f}" for f in _TRANSLATE_JP] +
    [f"map/model/S{i:03d}/S{i:03d}.nif" for i in range(1, 600)] +
    [f"map/model/S{i:03d}/S{i:03d}.big" for i in range(1, 600)]
)


def build_hash_map(refs: list[str] = None, extra_paths: list[str] = None) -> dict[int, str]:
    """既知パス + refs + extra_paths からhash→パスのマップを構築"""
    hmap = {}

    def add(raw: str):
        fn, pt = normalize(raw)
        if fn:
            h = calc_hash(fn, pt)
            if h not in hmap:
                hmap[h] = raw

    for p in _STATIC_PATHS:
        add(p)
    for p in (extra_paths or []):
        add(p)
    for fname in (refs or []):
        for path in _guess_paths(fname):
            add(f"{path}/{fname}")

    return hmap


def _guess_paths(fname: str) -> list[str]:
    """ファイル名からディレクトリ候補を返す"""
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

    if fl in {f.lower() for f in _DATA_DB}:
        paths.append("data/db")

    return paths


# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="AstralTale NFS 展開済みファイル リネームツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python nfs_rename.py --out D:\\work\\out --dry-run
  python nfs_rename.py --out D:\\work\\out --refs refs.txt --copy
  python nfs_rename.py --out D:\\work\\out --refs refs.txt --paths extra.txt
"""
    )
    parser.add_argument("--out",     required=True,
                        help="展開済みファイルのフォルダ")
    parser.add_argument("--refs",    default=None,
                        help="iniから抽出したファイル名リスト (refs.txt)")
    parser.add_argument("--paths",   default=None,
                        help="フルパス形式の追加パスリスト")
    parser.add_argument("--dry-run", action="store_true",
                        help="確認のみ（実際には何もしない）")
    parser.add_argument("--copy",    action="store_true",
                        help="リネームではなくコピー（元ファイルを残す・推奨）")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="詳細ログ（全ファイルを表示）")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[ERROR] フォルダが見つかりません: {out_dir}")
        return

    # refs.txt 読み込み
    refs = []
    if args.refs:
        with open(args.refs, 'r', encoding='utf-8-sig') as f:
            refs = [l.strip() for l in f if l.strip()]
        print(f"[INFO] refs.txt: {len(refs):,} 件")

    # 追加パスリスト読み込み
    extra = []
    if args.paths:
        with open(args.paths, 'r', encoding='utf-8') as f:
            extra = [l.strip() for l in f if l.strip()]
        print(f"[INFO] 追加パス: {len(extra):,} 件")

    # ハッシュマップ構築
    print("[INFO] ハッシュマップ構築中...")
    hmap = build_hash_map(refs, extra)
    print(f"[INFO] {len(hmap):,} パターン生成")

    # 展開済みファイルを取得
    exts = ['*.dds', '*.nif', '*.ini', '*.txt', '*.bin', '*.kf',
            '*.kfm', '*.smp', '*.pmap', '*.png', '*.bmp', '*.jpg', '*.xml']
    files = []
    for ext in exts:
        files += list(out_dir.glob(ext))
    print(f"[INFO] 対象ファイル: {len(files):,} 件")
    print("-" * 60)

    renamed = skipped = unknown = 0

    for f in sorted(files):
        try:
            h = int(f.stem, 16)
        except ValueError:
            if args.verbose:
                print(f"  [SKIP] {f.name} (既にリネーム済み)")
            skipped += 1
            continue

        if h not in hmap:
            if args.verbose:
                print(f"  [----] {f.name}")
            unknown += 1
            continue

        known_raw = hmap[h]
        fn, pt    = normalize(known_raw)
        orig_ext  = f.suffix.lower()
        base_name = fn.rsplit('.', 1)[0] if '.' in fn else fn
        final     = base_name + orig_ext
        new_dir   = out_dir / pt.replace('/', os.sep) if pt else out_dir
        new_path  = new_dir / final

        if args.dry_run:
            print(f"  [DRY] {f.name} → {pt+'/' if pt else ''}{final}")
            renamed += 1
            continue

        new_dir.mkdir(parents=True, exist_ok=True)

        if new_path.exists():
            if args.verbose:
                print(f"  [SKIP] {final} (既に存在)")
            skipped += 1
            continue

        if args.copy:
            shutil.copy2(f, new_path)
        else:
            f.rename(new_path)

        renamed += 1
        if args.verbose or renamed % 200 == 0:
            print(f"  [{renamed:>5}] {f.name} → {pt+'/' if pt else ''}{final}")

    print("-" * 60)
    action = "DRY RUN" if args.dry_run else ("コピー" if args.copy else "リネーム")
    print(f"[完了] {action}: {renamed:,} 件")
    print(f"       未特定: {unknown:,} 件  スキップ: {skipped:,} 件")


if __name__ == "__main__":
    main()
