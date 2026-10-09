"""trick_status.py [--write]

Skate 3's own list of tricks (the scoring table, 300 names in 14 classes) against what the skateboard controller
can do. Prints what is in and what is still missing, class by class; --write also writes TRICKS.md beside MODLOG.md.

DONE below is kept by hand as families are built, in the scoring table's own names. Every name in it must exist in
the table (a typo fails the run), and `ridetest.py` rides examples of each family; this file only does the counting.
"""
import io
import json
import os
import sys

import paths  # noqa: E402
VAULT = paths.work(r"vlt\dump\scoring_trick.json")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

FLIPS = ['kickflip', 'heelflip', 'popshuvit', 'fspopshuvit', 'varialkickflip', 'varialheelflip', 'hardflip',
         'inwardheelflip', '360popshuvit', 'fs360popshuvit', '360flip', 'laserflip', '360hardflip', '360inwardheelflip']
DONE = {}


def done(why, names):
    for n in names:
        DONE[n] = why


done('flick', ['ollie', 'nollie'] + FLIPS + ['n_' + f for f in FLIPS])
done('flick in the air', ['latekickflip', 'lateheelflip', 'latebackfootkickflip', 'latebackfootheelflip',
                          'latebsshuv', 'latefsshuv'])
done('trigger in the air (stick up / down first for the tail / nose side)',
     ['fsgrab', 'bsgrab', 'dblgrab', 'tailgrab', 'nosegrab', 'crailgrab', 'seatbeltgrab'])
done('land on a rail or ledge', ['fs_50_50', 'bs_50_50', 'fs_5_o', 'bs_5_o', 'fs_nosegrind', 'bs_nosegrind', 'fs_crook',
                                 'bs_crook', 'fs_smith', 'bs_smith', 'fs_feeble', 'bs_feeble', 'fs_board', 'bs_board',
                                 'fs_lip', 'bs_lip', 'fs_noseslide', 'bs_noseslide', 'fs_tailslide', 'bs_tailslide'])
done('right stick held part way', ['tailmanual', 'nosemanual'])
# 2026-10-06: family 1
done('trigger on the ground', ['gnd_fsgrab', 'gnd_bsgrab', 'gnd_dblgrab'])
done('both triggers, then both push buttons', ['coffin'])
# 2026-10-06: family 2
for base in ('kickflip', 'heelflip', 'n_kickflip', 'n_heelflip'):
    done('the flick held (2 / 3 / 4 flips)', [base + str(n) for n in (2, 3, 4)])
    done('a second flick during the flip', [base + n + '_underflip' for n in ('', '2', '3', '4')])
    done('a push button during the flip', [base + n + '_darkcatch' for n in ('', '2', '3', '4')])
done('a second flick during the shuvit', [p + '_underflip' for p in ('popshuvit', 'fspopshuvit', 'n_popshuvit', 'n_fspopshuvit')])
done('a push button during the flip', [p + f + '_darkcatch' for p in ('', 'n_')
                                       for f in ('360flip', 'laserflip', '360hardflip', '360inwardheelflip')])
done('a late flip with the board caught upside down', ['darktolightkickflip', 'darktolightheelflip', 'darktolightbsshuv',
                                                       'darktolightfsshuv'])
done('a late flip with a push button held', ['lateflip_darkcatch'])
done('a push button held in a plain jump', ['ollie_onefoot_front', 'ollie_onefoot_back'])
# 2026-10-06: family 3
done('the stick to the FS-shifty side, then a trigger', ['mutegrab', 'stalegrab'])
done('the stick moved while grabbing', [g + '_' + d for g in ('fsgrab', 'bsgrab') for d in ('up', 'down', 'left', 'right')]
     + [g + '_' + d for g in ('mutegrab', 'stalegrab') for d in ('up', 'down', 'left')]
     + [g + '_' + d for g in ('tailgrab', 'nosegrab', 'crailgrab', 'seatbeltgrab') for d in ('left', 'right')])
done('a push button while grabbing', ['fs_onefoot_right', 'fs_backfoot', 'bs_onefoot_behind', 'bs_onefoot_front',
                                      'tailgrab_onefoot_front', 'tailgrab_onefoot_behind', 'nosegrab_onefoot_front',
                                      'nosegrab_onefoot_behind'])
done('Y while grabbing (or both push buttons on a tail / nose grab)', ['nofoot_air', 'christ_air', 'superman', 'tailgrab_airwalk',
                                                                    'nosegrab_airwalk'])
done('the other hand as well on a nose grab', ['rocketair'])
done('a flick of the right stick while grabbing',
     ['fsgrab_fingerflip', 'bsgrab_fingerflip', 'mutegrab_fingerflip', 'stalegrab_fingerflip', 'nosegrab_fingerflip',
      'tailgrab_fingerflip', 'bsgrabtomutegrab_fingerflip', 'fsgrabtostalegrab_fingerflip', 'mutegrabtobsgrab_fingerflip',
      'stalegrabtofsgrab_fingerflip', 'bsgrabvarial_fingerflip', 'fsgrabvarial_fingerflip', 'crailtotail_fingerflip',
      'seatbelttonose_fingerflip'])
# 2026-10-06: family 4
for side in ('fs_', 'bs_'):
    done('land on a rail at an angle: the truck on it and the way the nose points', [side + g for g in ('overcrook', 'salad', 'willy', 'overwilly')])
    done('across the rail on the nose or tail, the board gone over it', [side + 'blunt', side + 'noseblunt'])
    done('a board caught upside down landed on a rail', [side + 'darkslide'])
    done('a trigger while grinding', [side + g for g in (
        '50_50_fsgrab', '50_50_bsgrab', '5_o_fsgrab', '5_o_nosegrab', 'crook_bsgrab', 'crook_tailgrab', 'overcrook_bsgrab',
        'overcrook_tailgrab', 'nosegrind_bsgrab', 'nosegrind_tailgrab', 'salad_fsgrab', 'salad_nosegrab', 'noseslide_tailgrab',
        'tailslide_nosegrab', 'blunt_tailgrab', 'noseblunt_tailgrab', 'board_double', 'board_nose', 'board_tail', 'lip_double',
        'lip_nose', 'lip_tail', 'darkslide_double', 'darkslide_nose', 'darkslide_tail')])
done('a flick on a darkslide', ['darkslideout_' + s + k for s in ('fs', 'bs') for k in ('left', 'right', 'straight')])
done('land on a rail coming straight at it (no side to name it by)',
     ['grind5050', 'grind5_o', 'grindnose', 'grindcrooks', 'grindfeeble', 'grindsmith', 'grindsalad', 'grindwilly',
      'grindoverwilly', 'slideboard', 'slidenose', 'slidetail'])
# 2026-10-06: family 5
done('a push button with one hand on the board on the ground (front foot / back foot)', ['fsboneless', 'bsboneless', 'fsfastplant', 'bsfastplant'])
done("the front foot's push button, then a flick", ['nocomply'])
done('both push buttons held, then let go', ['hippyjump'])
done('the left stick swept through a half circle', ['fsrevert', 'bsrevert'])
# what is not built, and why (shown under "Missing")
WHY = {
    'fspowerslide': "the game lets the wheels go by its physics (the Sliding state's only condition is CanEnterSlide), out of a hard "
                    "turn, a brake, a push, a manual or a crooked landing; our board has no sideways slip to let go. It is not the "
                    "right stick out to a side: that is where the 360 flips' own gestures start",
    'bspowerslide': "see fspowerslide",
    'fsgrab_fs_footplant': "a foot pushed off a wall in the air (IsFootPlanting): needs the walls the board cannot ride yet",
    'fsgrab_bs_footplant': "see fsgrab_fs_footplant", 'bsgrab_fs_footplant': "see fsgrab_fs_footplant",
    'bsgrab_bs_footplant': "see fsgrab_fs_footplant",
    'fs_handplant': "a hand on the coping of a quarter pipe (IsHandPlanting): needs the board to ride up a wall and come back",
}
# names in the table that the controller cannot give, and why
NEVER = {
    'grindovercrooks': 'an overcrook is told from a crooked grind by the side the rider came from; with the side known it is fs_ / bs_overcrook',
    'slidelip': 'a lipslide is told from a boardslide by the side; with the side known it is fs_ / bs_lip',
    'slideblunt': 'a blunt slide is told from a tail slide by the side; with the side known it is fs_ / bs_blunt',
    'slidenblunt': 'a nose blunt is told from a nose slide by the side; with the side known it is fs_ / bs_noseblunt',
}


def main():
    d = json.load(io.open(VAULT, encoding='utf-8'))
    cols = d['collections']
    classes = {n for n in cols if n.endswith('_class')}
    # (some collections are only the parent of a FS and a BS trick, grind5050 of fs_50_50 and bs_50_50: not tricks)
    parents = {c.get('parent') for c in cols.values()}
    tricks = {}
    for name, c in cols.items():
        if name in classes or name in parents:
            continue
        parent = c.get('parent')
        while parent and parent not in classes and parent in cols:
            parent = cols[parent].get('parent')
        tricks[name] = parent or '(none)'
    unknown = sorted(n for n in DONE if n not in tricks)
    if unknown:
        sys.exit('DONE names that are not in the scoring table: ' + ' '.join(unknown))
    lines = ['# Skate 3 tricks: what the skateboard can do', '',
             'Skate 3\'s own list (its scoring table) against the controller. Written by `skate3-sp/tools/trick_status.py`.',
             '']
    total = have = 0
    for cls in sorted(set(tricks.values())):
        names = sorted(n for n, p in tricks.items() if p == cls)
        got = [n for n in names if n in DONE]
        miss = [n for n in names if n not in DONE and n not in NEVER]
        never = [n for n in names if n in NEVER]
        total += len(names)
        have += len(got)
        lines.append('## %s: %d of %d' % (cls, len(got), len(names)))
        if got:
            lines.append('In: ' + ', '.join(got))
        if miss:
            lines.append('')
            lines.append('**Missing: ' + ', '.join(miss) + '**')
            for n in miss:
                if n in WHY and not WHY[n].startswith('see '):
                    lines.append('')
                    lines.append('Why not: `%s` and its like: %s.' % (n, WHY[n]))
        for n in never:
            lines.append('')
            lines.append('Not given: `%s` (%s).' % (n, NEVER[n]))
        lines.append('')
    lines.insert(3, '**%d of %d tricks.**' % (have, total))
    text = '\n'.join(lines) + '\n'
    print('%d of %d tricks' % (have, total))
    for l in lines:
        if l.startswith('## ') or l.startswith('**Missing'):
            print(l if len(l) < 400 else l[:400] + ' ...')
    if '--write' in sys.argv:
        io.open(os.path.join(ROOT, 'TRICKS.md'), 'w', encoding='utf-8', newline='\n').write(text)
        print('wrote TRICKS.md')


if __name__ == '__main__':
    main()
