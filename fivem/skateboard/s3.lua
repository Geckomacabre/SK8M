-- Optional: real Skate 3 animations. This file contains no Skate 3 data, only clip NAMES. The clips themselves
-- come from `skate3_assets`, a local-only resource you build from your own copy of the game (skate3-sp/tools).
-- While that resource is running the rider is posed with Skate 3's clips, chained the way Skate 3's own motion
-- graph chains them (data/state/MotionGraphIncludes), and tricks are read from the stick with Skate 3's own Flick-It
-- patterns; without it the skateboard falls back to the stock GTA poses and the built-in stick reader.
--
-- Stance: Skate 3's on-board clips are authored GOOFY (right foot forward) and the game itself plays them left-right
-- mirrored ("IsMirrored") for the other stance. So a regular rider plays the mirrored copies (<clip>_mir) that the
-- asset build adds, a goofy rider the clips as they are, and riding switch flips it again. The Flick-It stick is NOT
-- mirrored: like Skate 3, the same stick path is read against the same patterns and the trick is swapped for its
-- mirror twin (kickflip <-> heelflip ...) when the rider is mirrored.

S3 = { lift = 0.0, clip = nil, upper = nil, seq = 0, mirror = false }

local RES = 'skate3_assets'
local id            -- rider handle in skate3_assets while riding
local key           -- what the body is doing now ('ride', 'push', 'trick', 'grind', ...)
local steps, index, stepT, stepLen
local lean = 0.0
local live          -- the step clip shown for a 'lean' step: { base, k } (see playStep)
local turning       -- the versions of a 'turn' step and the one showing: { set = { l, c, r }, side }
local high = true   -- the trick in progress is the high version (fast flick)
local flipping = false -- the trick in progress turns the board (an ollie can't be under-flipped)
local prog          -- the flip in the air, clip by clip: { name, t = its TRICK entry, hl, stage, n = flips, win, ... }
local darkOn = false -- the board is upside down under the feet (caught dark)
local gvar          -- what is showing on top of the grab in hand: 'tw_up', 'foot_front', 'airwalk', 'nofoot', 'super', 'rocket'
local fingering = false -- a finger flip is turning the board
local grindGrab     -- a hand on the board on a rail: { hand, e = its GRAB entry, clip, stage = 'into' | 'cyc' | 'out', got }
local slideOut      -- popping off a darkslide: { key, label } for the jump it makes
local planting      -- a foot plant off the ground in progress: { d = its PLANT entry, class }
local afterPlant = false -- the jump is a foot plant's: a hand still on the board goes on with the grab's cycle
local lengths, names = {}, {}
local gesture       -- { name, step = 1 into | 2 loop | 3 out, t, len } while the arms do a gesture
local gestureIndex = 0
local patterns      -- Skate 3's Flick-It patterns (from skate3_assets), nil = use the built-in stick reader
local grindKey      -- which grind clip set is playing
local pushKind      -- which push clips are playing ('slow', 'fast_mongo', ...)
local cutNext = false -- start the next clip without a cross-fade (the pose it starts in is already showing)
local skitchNow       -- the clip showing while holding on to a car (see skitchClip)

local LEAN_STEPS = 9 -- <lean clip>_s0 (full left) .. _s4 (upright) .. _s8 (full right), static poses

-- ------------------------------------------------------------------ tricks

-- Skate 3's trick names (the gesture names in data/joystick/skater.pat, also its motion-graph intents).
--   clip:  <clip>_<low|high>_g = takeoff on the ground, <clip>_<low|high>_a = in the air
--          (Tricks.xml: T_Trick / T_TrickWithDarkCatch / T_TrickWithUnderflip play _G then _A)
--   out:   kickflips and heelflips add the catch (T_Kickflip: In -> Out1), with <hi|low> in its name
--   swap:  the trick the same stick path gives a mirrored rider (ActionGraphIncludes/T_Trick.xml, "Switch" state)
--   label: the name shown on screen
--   multi: kickflips and heelflips (Tricks/T_Kickflip.xml). The takeoff's air clip is half a flip; then either the
--          catch (out1) or, with the flick held and time enough left to fall, the flip goes on: cyc1 > out2 is a
--          double, cyc1 > cyc2 > out3 a triple, ... > cyc3 > out4 a quad. uflip / dcatch = the clip that takes over
--          for an underflip (a second flick: the board is kicked back the other way, and `other`'s catch ends it) or
--          a dark catch (a push button: the board is caught upside down) after half a flip, one and a half, ...
--   uflip: shuvits have one underflip (T_TrickWithUnderflip.xml); dcatch: the 360 flips one dark catch
--          (T_TrickWithDarkCatch.xml). Both take the high / low word (dlow = the low word where it is not 'low').
local TRICK = {
    Ollie                 = { clip = 'ollie',                label = 'Ollie' },
    Kickflip              = { clip = 'kickflip_in',          label = 'Kickflip', swap = 'Heelflip',
                              multi = { cyc = 't_%s_kick_cyc%d', out = 't_kickflip_%s_4flips_0_out%d', out4 = 't_%s_kick_out4',
                                        uflip = 't_kickflip_%s_uflip_0_out%d', dcatch = 't_kickflip_%s_dcatch_0_out%d',
                                        other = 'Heelflip' } },
    Heelflip              = { clip = 'heelflip_in',          label = 'Heelflip', swap = 'Kickflip',
                              multi = { cyc = 't_%s_heel_cyc%d', out = 't_heelflip_%s_4flips_0_out%d', out4 = 't_%s_heel_out4',
                                        uflip = 't_heelflip_%s_uflip_out%d', dcatch = 't_heelflip_%s_dcatch_out%d',
                                        other = 'Kickflip' } },
    PopShuvit             = { clip = 'popshuvit',            label = 'Pop Shuvit', swap = 'FSPopShuvit',
                              uflip = 't_popshuvit_%s_uflip_out1' },
    FSPopShuvit           = { clip = 'fspopshuvit_d',        label = 'FS Pop Shuvit', swap = 'PopShuvit',
                              uflip = 't_fspopshuvit_%s_uflip_out1' },
    VarialKickflip        = { clip = 'varialkickflip',       label = 'Varial Kickflip', swap = 'VarialHeelflip' },
    VarialHeelflip        = { clip = 'varialheelflip_d',     label = 'Varial Heelflip', swap = 'VarialKickflip' },
    Hardflip              = { clip = 'hardflip',             label = 'Hardflip', swap = 'InwardHeelflip' },
    InwardHeelflip        = { clip = 'inwardheelflip',       label = 'Inward Heelflip', swap = 'Hardflip' },
    ['360PopShuvit']      = { clip = '360popshuvit',         label = '360 Pop Shuvit', swap = 'FS360PopShuvit' },
    FS360PopShuvit        = { clip = 'fs360popshuvit',       label = 'FS 360 Pop Shuvit', swap = '360PopShuvit' },
    ['360Flip']           = { clip = '360flip_d',            label = '360 Flip', swap = 'Laserflip',
                              dcatch = 't_360flip_%s_dcatch_out1' },
    Laserflip             = { clip = 'laserflip',            label = 'Laser Flip', swap = '360Flip',
                              dcatch = 't_laserflip_%s_dcatch_out1' },
    ['360Hardflip']       = { clip = '360hardflip',          label = '360 Hardflip', swap = '360InwardHeelflip',
                              dcatch = 't_360hardflip_%s_dcatch_out1' },
    ['360InwardHeelflip'] = { clip = '360inwardheelflip',    label = '360 Inward Heelflip', swap = '360Hardflip',
                              dcatch = 't_360inwardheelflip_%s_dcatch_out1' },
    Nollie                = { clip = 'nollie',               label = 'Nollie', nose = true },
    N_Kickflip            = { clip = 'n_kickflip_in',        label = 'Nollie Kickflip', swap = 'N_Heelflip', nose = true,
                              multi = { cyc = 't_%s_n_kick_cyc%d', out = 't_n_kickflip_%s_4flips_0_out%d', out4 = 't_%s_n_kick_out4',
                                        uflip = 't_n_kickflip_%s_uflip_out%d', dcatch = 't_n_kickflip_%s_dcatch_out%d',
                                        other = 'N_Heelflip' } },
    N_Heelflip            = { clip = 'n_heelflip_in',        label = 'Nollie Heelflip', swap = 'N_Kickflip', nose = true,
                              multi = { cyc = 't_%s_n_heel_cyc%d', out = 't_n_heelflip_%s_4flips_0_out%d', out4 = 't_%s_n_heel_out4',
                                        uflip = 't_n_heelflip_%s_uflip_out%d', dcatch = 't_n_heelflip_%s_dcatch_out%d',
                                        other = 'N_Kickflip' } },
    N_PopShuvit           = { clip = 'n_popshuvit',          label = 'Nollie Pop Shuvit', swap = 'N_FSPopShuvit', nose = true,
                              uflip = 't_n_popshuvit_%s_uflip_out1' },
    N_FSPopShuvit         = { clip = 'n_fspopshuvit',        label = 'Nollie FS Pop Shuvit', swap = 'N_PopShuvit', nose = true,
                              uflip = 't_n_fspopshuvit_%s_uflip_out1' },
    N_VarialKickflip      = { clip = 'n_varialkickflip',     label = 'Nollie Varial Kickflip', swap = 'N_VarialHeelflip', nose = true },
    N_VarialHeelflip      = { clip = 'n_varialheelflip',     label = 'Nollie Varial Heelflip', swap = 'N_VarialKickflip', nose = true },
    N_Hardflip            = { clip = 'n_hardflip',           label = 'Nollie Hardflip', swap = 'N_InwardHeelflip', nose = true },
    N_InwardHeelflip      = { clip = 'n_inwardheelflip',     label = 'Nollie Inward Heelflip', swap = 'N_Hardflip', nose = true },
    N_360PopShuvit        = { clip = 'n_360popshuvit',       label = 'Nollie 360 Pop Shuvit', swap = 'N_FS360PopShuvit', nose = true },
    N_FS360PopShuvit      = { clip = 'n_fs360popshuvit',     label = 'Nollie FS 360 Pop Shuvit', swap = 'N_360PopShuvit', nose = true },
    N_360Flip             = { clip = 'n_360flip',            label = 'Nollie 360 Flip', swap = 'N_Laserflip', nose = true,
                              dcatch = 't_n_360flip_%s_dcatch_out1' },
    N_Laserflip           = { clip = 'n_laserflip',          label = 'Nollie Laser Flip', swap = 'N_360Flip', nose = true,
                              dcatch = 't_n_laserflip_%s_dcatch_out1', dlow = 'lo' },
    N_360Hardflip         = { clip = 'n_360hardflip',        label = 'Nollie 360 Hardflip', swap = 'N_360InwardHeelflip', nose = true,
                              dcatch = 't_n_360hardflip_%s_dcatch_out1' },
    N_360InwardHeelflip   = { clip = 'n_360inwardheelflip',  label = 'Nollie 360 Inward Heelflip', swap = 'N_360Hardflip', nose = true,
                              dcatch = 't_n_360inwardheelflip_%s_dcatch_out1', dlow = 'lo' },
}

-- Late flips: flicked in the air (data/joystick/skater_air.pat). clip takes the high / low word.
local LATE = {
    L_F_Kickflip = { label = 'Late Kickflip', clip = 't_late_kickflip_%s_0_n', hi = 'hi', low = 'low', swap = 'L_F_Heelflip' },
    L_F_Heelflip = { label = 'Late Heelflip', clip = 't_late_heelflip_%s_0_n', hi = 'hi', low = 'low', swap = 'L_F_Kickflip' },
    L_B_Kickflip = { label = 'Late Back Foot Kickflip', clip = 't_late_backfootkick%s_n_0_n', hi = 'hi', low = 'low',
                     swap = 'L_B_Heelflip' },
    L_B_Heelflip = { label = 'Late Back Foot Heelflip', clip = 't_late_backfootheel%s_n_0_n', hi = 'hi', low = 'low',
                     swap = 'L_B_Kickflip' },
    L_FS_Shuvit  = { label = 'Late FS Shuvit', clip = 't_late_shuvit%s_fs_0_n', hi = 'high', low = 'low', swap = 'L_BS_Shuvit' },
    L_BS_Shuvit  = { label = 'Late Shuvit', clip = 't_late_shuvit%s_bs_0_n', hi = 'high', low = 'low', swap = 'L_FS_Shuvit' },
}

local function trickClips(name, isHigh)
    local t = TRICK[name] or TRICK.Ollie
    local base = t.clip .. (isHigh and '_high' or '_low')
    return base .. '_g', base .. '_a'
end

local function lateClip(l, isHigh) return l.clip:format(isHigh and l.hi or l.low) end

-- A board caught upside down (a dark catch) is flicked the right way up again with the late-flip gestures
-- (air.xml "DarkToLightflip"): which clip each gives, the name it scores under, and what a mirrored rider gets.
local DARK_OUT = {
    kickflip = { clip = 't_darktolight_kickflip_%s', key = 'darktolightkickflip', label = 'Dark to Light Kickflip', swap = 'heelflip' },
    heelflip = { clip = 't_darktolight_heelflip_%s', key = 'darktolightheelflip', label = 'Dark to Light Heelflip', swap = 'kickflip' },
    bsshuv   = { clip = 't_darktolight_bsshuvit_%s', key = 'darktolightbsshuv', label = 'Dark to Light Shuvit', swap = 'fsshuv' },
    fsshuv   = { clip = 't_darktolight_fsshuvit_%s', key = 'darktolightfsshuv', label = 'Dark to Light FS Shuvit', swap = 'bsshuv' },
}
local DARK_GESTURE = { L_F_Kickflip = 'kickflip', L_B_Kickflip = 'kickflip', L_F_Heelflip = 'heelflip', L_B_Heelflip = 'heelflip',
                       L_BS_Shuvit = 'bsshuv', L_FS_Shuvit = 'fsshuv' }
-- a late flip with the dark-catch button held is caught upside down (air.xml "DarkLateflip")
local DARK_LATE = 't_ds_late_heelflip_%s_0_n'

-- ------------------------------------------------------------------ grinds and slides
-- Skate 3 picks the grind from where the board touches the rail; its clips always have the board along the
-- rider, so the angle to the rail is in the rider's heading. Per grind:
--   t        clip family (g_<t>_<set>_<hi|low>_<l|0|r>_cyc)
--   s, h     which part of the board is on the rail: s metres from the middle of the deck towards the nose, with
--            the deck top h above the contact (a truck: 0.07, the wood: 0.015). truck = that part is a truck: the
--            ride says how far from the middle the trucks are
--   fs, bs   the clip set for each side; fakie = the "bf" (backward-facing) sets
--   turn     the rider's heading relative to the direction of travel, degrees to the LEFT, for the clips as
--            authored (goofy); mirrored clips turn the other way. Slides are +-90: `fwd` names the side whose clip
--            travels towards the rider's chest (the others travel back first), measured from the clips themselves
--            and the same as real skateboarding (BS boardslide, FS lipslide, BS noseslide, FS tailslide face forward).
--   An "over" grind is the pose of the other side's (Grinds.xml: FS_OVERCROOK plays B_BS_GRINDCROOKS): swap.
--   A blunt slide has the board gone over the rail: on a ledge its own clips (the wheels on top), on a round rail
--   the other side's tail / nose slide (T_BluntGrind.xml: ALT_ANIM unless "IsGrindBluntingBackslash"): rail.
--   dark = the board is upside down (a dark catch landed on a rail).
--   key  = the grind's name in Skate 3's scoring table, after the side (fs_50_50)
--   gen  = ... and its name there when the side is not known (the rider came straight at the rail)
--   grab = a trigger held on the grind (grinding.xml: the back hand = "GrindFSGrab", the front "GrindBSGrab", both
--          "GrindDoubleGrab"; Grinds/*.xml): { clip (<clip>_into / _cyc / _out; %s = the side), what it adds to the
--          grind's name in the scoring table, what it is called; bf = the clip riding backwards, rail = on a round rail
--          (the other side's) }. grabSwap: a lipslide's are the boardslide's of the other side.
local GRIND = {
    ['50-50']         = { key = '50_50', gen = 'grind5050', grab = { fs = { 'g_5050_fs_grab', 'fsgrab', 'FS Grab', bf = 'g_5050_bf_fsgrab' },
                          bs = { 'g_5050_bs_grab', 'bsgrab', 'BS Grab', bf = 'g_5050_bf_bsgrab' } },
                          t = '5050',     s = 0.0,   h = 0.07,  fs = 'fs', bs = 'fs', fakie = 'bf', label = '50-50' },
    ['5-0']           = { key = '5_o', gen = 'grind5_o', grab = { fs = { 'g_50_fs_hi_grab', 'fsgrab', 'FS Grab', bf = 'g_50_bf_hi_fsgrab' },
                          bs = { 'g_50_bs_hi_grab_nose', 'nosegrab', 'Nose Grab', bf = 'g_50_bf_hi_bsgrab_nose' } },
                          t = '50',       s = -0.26, h = 0.07,  fs = 'bs', bs = 'bs', fakie = 'bf', label = '5-0', truck = true },
    ['Nosegrind']     = { key = 'nosegrind', gen = 'grindnose', grab = { fs = { 'g_ngrind_hi_grab_tail', 'tailgrab', 'Tail Grab', bf = 'g_ngrind_bf_hi_grab_tail' },
                          bs = { 'g_ngrind_hi_grab_bs', 'bsgrab', 'BS Grab', bf = 'g_ngrind_bf_hi_grab_bs' } },
                          t = 'ngrind',   s = 0.26,  h = 0.07,  fs = 'bs', bs = 'bs', fakie = 'bf', label = 'Nosegrind', truck = true },
    ['Crooked']       = { key = 'crook', gen = 'grindcrooks', grab = { fs = { 'g_crooks_%s_grab_tail', 'tailgrab', 'Tail Grab', bf = 'g_crooks_bf_%s_grab_tail' },
                          bs = { 'g_crooks_%s_grab_bs', 'bsgrab', 'BS Grab', bf = 'g_crooks_bf_%s_grab_bs' } },
                          t = 'crooks',   s = 0.26,  h = 0.07,  fs = 'fs', bs = 'bs', fakie = 'bf_%s', label = 'Crooked Grind',
                          truck = true, turn = { fs = 20.0, bs = -20.0 } },
    ['Smith']         = { key = 'smith', gen = 'grindsmith',
                          t = 'smith',    s = -0.26, h = 0.07,  fs = 'fs', bs = 'bs', fakie = 'bf_%s', label = 'Smith Grind',
                          truck = true, turn = { fs = -20.0, bs = 20.0 } },
    ['Feeble']        = { key = 'feeble', gen = 'grindfeeble',
                          t = 'feeble',   s = -0.26, h = 0.07,  fs = 'fs', bs = 'bs', fakie = 'bf_%s', label = 'Feeble Grind',
                          truck = true, turn = { fs = 20.0, bs = -20.0 } },
    ['Overcrook']     = { key = 'overcrook', gen = 'grindovercrooks', grab = { fs = { 'g_crooks_%s_grab_tail', 'tailgrab', 'Tail Grab', bf = 'g_crooks_bf_%s_grab_tail' },
                          bs = { 'g_crooks_%s_grab_bs', 'bsgrab', 'BS Grab', bf = 'g_crooks_bf_%s_grab_bs' } },
                          t = 'crooks',   s = 0.26,  h = 0.07,  fs = 'bs', bs = 'fs', fakie = 'bf_%s', label = 'Overcrook Grind',
                          truck = true, turn = { fs = -20.0, bs = 20.0 }, swap = true },
    ['Salad']         = { key = 'salad', gen = 'grindsalad', grab = { fs = { 'g_salad_%s_grab_fs', 'fsgrab', 'FS Grab', bf = 'g_salad_bf_%s_grab_fs' },
                          bs = { 'g_salad_%s_grab_nose', 'nosegrab', 'Nose Grab', bf = 'g_salad_bf_%s_grab_nose' } },
                          t = 'salad',    s = -0.26, h = 0.07,  fs = 'fs', bs = 'bs', fakie = 'bf_%s', label = 'Salad Grind',
                          truck = true, turn = { fs = 20.0, bs = -20.0 } },
    ['Willy']         = { key = 'willy', gen = 'grindwilly',
                          t = 'willy',    s = 0.26,  h = 0.07,  fs = 'bs', bs = 'bs', fakie = 'bf', label = 'Willy Grind',
                          truck = true, turn = { fs = 20.0, bs = -20.0 } },
    ['Overwilly']     = { key = 'overwilly', gen = 'grindoverwilly',
                          t = 'willy',    s = 0.26,  h = 0.07,  fs = 'bs', bs = 'bs', fakie = 'bf', label = 'Overwilly Grind',
                          truck = true, turn = { fs = -20.0, bs = 20.0 } },
    ['Boardslide']    = { key = 'board', gen = 'slideboard', grab = { fs = { 'g_bslide_%s_grab_tail', 'tail', 'Tail Grab' }, bs = { 'g_bslide_%s_grab_nose', 'nose', 'Nose Grab' },
                          dbl = { 'g_bslide_%s_grab_double', 'double', 'Double Grab' } },
                          t = 'bslide',   s = 0.0,   h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'bs', label = 'Boardslide' },
    ['Lipslide']      = { key = 'lip', gen = 'slidelip', grabSwap = true,
                          grab = { fs = { 'g_bslide_%s_grab_tail', 'tail', 'Tail Grab' }, bs = { 'g_bslide_%s_grab_nose', 'nose', 'Nose Grab' },
                          dbl = { 'g_bslide_%s_grab_double', 'double', 'Double Grab' } },
                          t = 'lipslide', s = 0.0,   h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'fs', label = 'Lipslide' },
    ['Noseslide']     = { key = 'noseslide', gen = 'slidenose', grab = { fs = { 'g_nslide_%s_grab_tail', 'tailgrab', 'Tail Grab' } },
                          t = 'nslide',   s = 0.36,  h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'bs', label = 'Noseslide' },
    ['Tailslide']     = { key = 'tailslide', gen = 'slidetail', grab = { bs = { 'g_tslide_%s_grab_nose', 'nosegrab', 'Nose Grab' } },
                          t = 'tslide',   s = -0.36, h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'fs', label = 'Tailslide' },
    ['Blunt']         = { key = 'blunt', gen = 'slideblunt', grab = { bs = { 'g_blunt_%s_grab_nose', 'tailgrab', 'Nose Grab', rail = 'g_tslide_%s_grab_nose' } },
                          t = 'blunt',    s = -0.36, h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'bs', label = 'Bluntslide',
                          rail = 'tslide' },
    ['Noseblunt']     = { key = 'noseblunt', gen = 'slidenblunt', grab = { fs = { 'g_nblunt_%s_grab_tail', 'tailgrab', 'Tail Grab', rail = 'g_nslide_%s_grab_tail' } },
                          t = 'nblunt',   s = 0.36,  h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'fs', label = 'Noseblunt Slide',
                          rail = 'nslide' },
    ['Darkslide']     = { key = 'darkslide', grab = { fs = { 'g_dslide_%s_grab_tail', 'tail', 'Tail Grab' }, bs = { 'g_dslide_%s_grab_nose', 'nose', 'Nose Grab' },
                          dbl = { 'g_dslide_%s_grab_double', 'double', 'Double Grab' } },
                          t = 'ds',       s = 0.0,   h = 0.015, fs = 'fs', bs = 'bs', slide = true, fwd = 'bs', label = 'Darkslide',
                          dark = true },
}
S3.GRINDS = GRIND

-- The clip family of a grind's grab: nil when that grind has no grab for that hand.
local function grindGrabClip(g, hand, side, fakie, onRail)
    local d = GRIND[g]
    local e = d and d.grab and d.grab[hand]
    if not e then return nil end
    local other = side == 'fs' and 'bs' or 'fs'
    if d.dark then return e[1]:format(side == 'bs' and 'b' or 'f'), e end -- (T_DarkGrind.xml: GRAB_ANIM = B / F)
    if onRail and e.rail then return e.rail:format(other), e end
    if fakie and e.bf then return e.bf:format(side), e end
    return e[1]:format(d.grabSwap and other or side), e
end

-- Off a darkslide by a flick (DarkSlideTrick): the board is kicked the right way up on the way out. A kickflip's
-- flick takes it out to the left, a heelflip's to the right, anything else straight.
local DARK_SLIDE_OUT = { Kickflip = { 'kickflip_out_lt', 'left', 'Darkslide Kickflip Out' },
                         Heelflip = { 'heelflip_out_rt', 'right', 'Darkslide Heelflip Out' } }
local DARK_SLIDE_STRAIGHT = { 'straight_out', 'straight', 'Darkslide Out' }

-- g = grind name, side = 'fs' | 'bs', bal = 'l' | '0' | 'r'; onRail = on a round rail, not on the edge of a ledge
local function grindClip(g, side, fakie, low, bal, onRail)
    local d = GRIND[g] or GRIND['50-50']
    local other = side == 'fs' and 'bs' or 'fs'
    local t, set = d.t, d[side] or side
    if fakie and d.fakie then set = d.fakie:format(d.swap and other or side) end
    if onRail and d.rail then t, set = d.rail, other end
    return ('g_%s_%s_%s_%s_cyc'):format(t, set, low and 'low' or 'hi', bal)
end

-- ------------------------------------------------------------------ foot plants off the ground, the hippy jump
-- Tricks.xml "PushTrick": out of a ground grab the push button of the front foot plants that foot (a boneless),
-- the back foot's the back foot (a fastplant); FS / BS = which hand is on the board. The front foot's push button
-- and then a flick is a no comply (ground.xml: Push.PushStart). Four clips each: the foot goes down (g), it is
-- planted (f), the board is lifted (l), and in the air it comes back under the feet (a). The game blends three
-- versions by the speed; we play the nearest.
local PLANT = {
    fsboneless  = { clip = 'boneless_fs_%s_%s',  label = 'FS Boneless',  classes = { 'stop', 'slow', 'fast' }, grab = 'fs' },
    bsboneless  = { clip = 'boneless_bs_%s_%s',  label = 'BS Boneless',  classes = { 'stop', 'slow', 'fast' }, grab = 'bs' },
    fsfastplant = { clip = 'fastplant_fs_%s_%s', label = 'FS Fastplant', classes = { 'stop', 'slow', 'fast' }, grab = 'fs' },
    bsfastplant = { clip = 'fastplant_bs_%s_%s', label = 'BS Fastplant', classes = { 'stop', 'slow', 'fast' }, grab = 'bs' },
    nocomply    = { clip = 'nocomply_l_%s_into_%s', label = 'No Comply', classes = { 'slow', 'med', 'fast' }, noGround = true },
}
-- The hippy jump (Tricks/T_HippyJump.xml): both push buttons held = the crouch, let go = the rider jumps and the
-- board rolls on under them. Its three heights have their own clips; the crouch's clips are one crouch cut off at
-- three depths, so how long the buttons were held picks the height.
local HIPPY = { 'mini', 'low', 'high' }
local HIPPY_CROUCH = { mini = 11 / 60, low = 21 / 60 } -- seconds of crouch a mini / low jump has behind it (the clips' lengths)

-- ------------------------------------------------------------------ grabs in the air
-- air.xml, T_Grab.xml, StaleMuteGrab.xml, BoardAdjust*.xml (which buttons), GrabsTweaks/*.xml, BoardAdjusts/*.xml
-- (which clips). The hands are the clips' as authored: the back hand is the LEFT one.
--   clip    <clip>_into / _cyc / _out; rate, outRate = how fast the game plays the first and the last
--   key     the grab's name in Skate 3's scoring table, label = on screen
--   tweak   the stick moved while grabbing: up / down / left / right = the clip held and what it is called. Left and
--           right are the way the NOSE goes (see the ride); tail / nose / crail / seatbelt have the two shifties
--   foot    a push button: that foot off the board (front / back = the rider's own): <clip>_0_into / _0_cyc / _0_out
--   nofoot  Y: both feet off (no-foot air on a FS grab, christ air on a BS grab); airwalk: Y or both push buttons on a
--           tail or nose grab; super: Y on a double grab (superman); rocket: the other hand as well on a nose grab
--   flip / var / shuv  finger flips, flicked with the right stick while grabbing: the board is flipped by hand and
--           caught again; shuv = { clip, the grab it ends in }
local GRAB = {
    fs = { clip = 'gr_grab_n_fs_0', rate = 2.0, outRate = 2.0, key = 'fsgrab', label = 'FS Grab',
           tweak = { up = { 'gr_nbone_n_fs_0_cyc', 'Nosebone' }, down = { 'gr_tbone_n_fs_0_cyc', 'Tailbone' },
                     left = { 'gr_stiffy_n_fs_0_cyc', 'Stiffy' }, right = { 'gr_tknee_n_fs_0_cyc', 'Tuck Knee' } },
           foot = { front = { '1ft_air_grab_n_fsr', 'fs_onefoot_right', 'FS Grab One Foot' },
                    back = { '1ft_air_grab_n_fsl', 'fs_backfoot', 'FS Grab Back Foot Off' } },
           nofoot = { 'gr_dsmnt_nofoot_fs', 'nofoot_air', 'No Foot Air', toSuper = 'gr_dsmnt_n_nofoot_to_super',
                      fromSuper = 'gr_dsmnt_n_super_to_nofoot' },
           flip = { 'f_flip_fs_grab', 'fsgrab_fingerflip', 'FS Grab Finger Flip' },
           var = { 'f_flip_fs_grab_varial', 'fsgrabvarial_fingerflip', 'FS Grab Varial Finger Flip' },
           shuv = { 'f_flip_fs_grab_to_stale', 'stale', 'fsgrabtostalegrab_fingerflip', 'FS Grab to Stalefish Finger Flip' } },
    bs = { clip = 'gr_grab_n_bs_0', rate = 2.0, outRate = 2.0, key = 'bsgrab', label = 'BS Grab',
           tweak = { up = { 'gr_melon_n_bs_0_cyc', 'Melon' }, down = { 'gr_japan_n_bs_0_cyc', 'Japan' },
                     left = { 'gr_cbone_n_bs_0_cyc', 'Cross Bone' }, right = { 'gr_method_n_bs_0_cyc', 'Method' } },
           foot = { front = { '1ft_air_grab_n_bsr', 'bs_onefoot_behind', 'BS Grab One Foot' },
                    back = { '1ft_air_grab_n_bsl', 'bs_onefoot_front', 'BS Grab Back Foot Off' } },
           nofoot = { 'gr_dsmnt_christ_bs', 'christ_air', 'Christ Air', toSuper = 'gr_dsmnt_n_christ_to_super',
                      fromSuper = 'gr_dsmnt_n_super_to_christ' },
           flip = { 'f_flip_bs_grab', 'bsgrab_fingerflip', 'BS Grab Finger Flip' },
           var = { 'f_flip_bs_grab_varial', 'bsgrabvarial_fingerflip', 'BS Grab Varial Finger Flip' },
           shuv = { 'f_flip_bs_grab_to_mute', 'mute', 'bsgrabtomutegrab_fingerflip', 'BS Grab to Mute Finger Flip' } },
    dbl = { clip = 'gr_grab_n_dbl_0', rate = 3.0, outRate = 2.0, key = 'dblgrab', label = 'Double Grab',
            tweak = { up = { 'gr_grab_n_dbl_fronttw_cyc' }, down = { 'gr_grab_n_dbl_backtw_cyc' },
                      left = { 'gr_grab_n_dbl_lefttw_cyc' }, right = { 'gr_grab_n_dbl_righttw_cyc' } },
            super = { 'gr_dsmnt_super_dbl', 'superman', 'Superman' } },
    tail = { clip = 'gr_tailgrab_n_bs_0', key = 'tailgrab', label = 'Tail Grab',
             tweak = { left = { 'gr_tailgrab_shifty_bs_0_cyc', 'BS Shifty Tail Grab' },
                       right = { 'gr_tailgrab_shifty_fs_0_cyc', 'FS Shifty Tail Grab' } },
             foot = { front = { '1ft_air_grab_n_tailr', 'tailgrab_onefoot_behind', 'Tail Grab One Foot' },
                      back = { '1ft_air_grab_n_taill', 'tailgrab_onefoot_front', 'Tail Grab Back Foot Off' } },
             airwalk = { '2ft_air_grab_n_tail', 'tailgrab_airwalk', 'Tail Grab Airwalk' },
             flip = { 'f_flip_tail_grab', 'tailgrab_fingerflip', 'Tail Grab Finger Flip' } },
    nose = { clip = 'gr_nosegrab_n_bs_0', key = 'nosegrab', label = 'Nose Grab',
             tweak = { left = { 'gr_nosegrab_shifty_bs_0_cyc', 'BS Shifty Nose Grab' },
                       right = { 'gr_nosegrab_shifty_fs_0_cyc', 'FS Shifty Nose Grab' } },
             foot = { front = { '1ft_air_grab_n_noser', 'nosegrab_onefoot_behind', 'Nose Grab One Foot' },
                      back = { '1ft_air_grab_n_nosel', 'nosegrab_onefoot_front', 'Nose Grab Back Foot Off' } },
             airwalk = { '2ft_air_grab_n_nose', 'nosegrab_airwalk', 'Nose Grab Airwalk' },
             rocket = { 'gr_nosegrab_rocketair_n', 'rocketair', 'Rocket Air' },
             flip = { 'f_flip_nose_grab', 'nosegrab_fingerflip', 'Nose Grab Finger Flip' } },
    crail = { clip = 'gr_crailgrab_n_0', rate = 1.2, key = 'crailgrab', label = 'Crail',
              tweak = { left = { 'gr_crailgrab_shifty_bs_0_cyc', 'BS Shifty Crail' },
                        right = { 'gr_crailgrab_shifty_fs_0_cyc', 'FS Shifty Crail' } },
              shuv = { 'f_flip_crail_to_tail_grab', 'tail', 'crailtotail_fingerflip', 'Crail to Tail Grab Finger Flip' } },
    seatbelt = { clip = 'gr_seatbeltgrab_n_0', rate = 1.2, key = 'seatbeltgrab', label = 'Seatbelt',
                 tweak = { left = { 'gr_seatbeltgrab_shifty_bs_0_cyc', 'BS Shifty Seatbelt' },
                           right = { 'gr_seatbeltgrab_shifty_fs_0_cyc', 'FS Shifty Seatbelt' } },
                 shuv = { 'f_flip_seatbelt_to_nose_grab', 'nose', 'seatbelttonose_fingerflip', 'Seatbelt to Nose Grab Finger Flip' } },
    mute = { clip = 'gr_mutegrab_n_0', rate = 1.25, key = 'mutegrab', label = 'Mute',
             tweak = { up = { 'gr_mutegrab_n_nose_cyc', 'Mute Nosebone' }, down = { 'gr_mutegrab_tail_n_0_cyc', 'Mute Tailbone' },
                       left = { 'gr_mutegrab_japan_n_0_cyc', 'Mute Tuck Knee' } },
             flip = { 'f_flip_mute_grab', 'mutegrab_fingerflip', 'Mute Finger Flip' },
             shuv = { 'f_flip_mute_to_bs_grab', 'bs', 'mutegrabtobsgrab_fingerflip', 'Mute to BS Grab Finger Flip' } },
    stale = { clip = 'gr_stalegrab_n_0', rate = 1.25, key = 'stalegrab', label = 'Stalefish',
              tweak = { up = { 'gr_stalegrab_nose_n_0_cyc', 'Stalefish Nosebone' }, down = { 'gr_stalegrab_tail_n_0_cyc', 'Stalefish Tailbone' },
                        left = { 'gr_stalegrab_tuckknee_n_0_cyc', 'Stalefish Tuck Knee' } },
              flip = { 'f_flip_stale_grab', 'stalegrab_fingerflip', 'Stalefish Finger Flip' },
              shuv = { 'f_flip_stale_to_fs_grab', 'fs', 'stalegrabtofsgrab_fingerflip', 'Stalefish to FS Grab Finger Flip' } },
}
-- one grab straight to another (GR_FS2DBL_0_TR ...): the second hand goes on, or one comes off
local GRAB_TR = { fs2dbl = 'gr_fs2dbl_0_tr', bs2dbl = 'gr_bs2dbl_0_tr', dbl2fs = 'gr_dbl2fs_0_tr', dbl2bs = 'gr_dbl2bs_0_tr' }
-- which gestures flick the board by hand (T_Grab.xml, T_StaleMuteFingerFlips.xml, BoardAdjustUp / Down.xml)
local FINGER = { Fingerflip = true, L_F_Kickflip = true, L_F_Heelflip = true, L_B_Kickflip = true, L_B_Heelflip = true }
local VARIAL = { FS_Varial = 'fs', BS_Varial = 'bs' }
local TIP_SHUV = { FS_Varial = true, BS_Varial = true, L_FS_Shuvit = true, L_BS_Shuvit = true }

-- The variant of a grab ('tw_up', 'foot_front', 'airwalk', 'nofoot', 'super', 'rocket'): its entry in the table.
local function grabVar(kind, v)
    local d = GRAB[kind]
    if not d or not v then return nil end
    local dir = v:match('^tw_(%a+)$')
    if dir then return d.tweak and d.tweak[dir] or nil, true end
    local foot = v:match('^foot_(%a+)$')
    if foot then return d.foot and d.foot[foot] or nil end
    return d[v]
end

-- Does this grab have that variant? (for the ride, which reads the buttons)
function S3.grabHas(kind, v) return grabVar(kind, v) ~= nil end

-- What a grab, or a variant of it, is called: the name in the scoring table and the name on screen. A tweak's name
-- in the table is the grab's with the direction on it (fsgrab_up); only some have one.
function S3.grabName(kind, v)
    local d = GRAB[kind]
    if not d then return nil end
    if not v then return d.key, d.label end
    local e, tweak = grabVar(kind, v)
    if not e then return nil end
    if tweak then
        if not e[2] then return d.key, d.label end
        return d.key .. '_' .. v:sub(4), e[2]
    end
    return e[2], e[3]
end

-- ------------------------------------------------------------------ body states

-- Each state is a chain of clips; the last one loops until the state changes.
-- { clip, blend seconds, 'loop' | 'lean' (follows the steering lean) | 'turn' | nil (play once), playback speed }
-- Blend times and playback speeds are the motion graph's (ground.xml, Anticipations/*.xml, Brake.xml, Push.xml,
-- Landing.xml, air.xml, GroundGrabs/*.xml).
-- A clip may come in three versions, for carving left, going straight and carving right (the game blends between
-- them): tri(left, straight, right). A one-shot plays the version the steering asks for when it starts; a 'turn'
-- step loops and changes over as the steering does.
local function tri(l, c, r) return { l = l, c = c, r = r } end

local CHAIN = {
    ride        = { { 'r_lean_hcom', 0.2, 'lean' } },
    -- standing still with a foot down (Brake.xml "Stationary"): from rolling, and straight out of the foot brake
    stand       = { { 'r_stand_idle2_n_0_into', 0.2 }, { 'r_stand_idle2_n_0_cyc', 0.2, 'loop' } },
    stand_from_brake = { { 'r_stand_fromlsbrake_n_0_tr', 0.2 }, { 'r_stand_idle2_n_0_cyc', 0.2, 'loop' } },
    -- the crouch before a pop: B_ANTIC_INTO then the cycle for where the stick is held (AnticCyc.xml)
    -- (the crouch goes in at 1.2 times its speed: Anticipation.AnticInto, "B_ANTIC_INTO time=0.2 playBackSpeed=1.2")
    antic_ollie    = { { 'r_antic_ollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_ollie', 0.3, 'lean' } },
    antic_shuv     = { { 'r_antic_ollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_360shuvit', 0.3, 'lean' } },
    antic_fsshuv   = { { 'r_antic_ollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_fs360shuvit', 0.3, 'lean' } },
    antic_nollie   = { { 'r_antic_nollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_nollie', 0.3, 'lean' } },
    antic_nshuv    = { { 'r_antic_nollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_n360shuvit', 0.3, 'lean' } },
    antic_nfsshuv  = { { 'r_antic_nollie_n_0_into', 0.2, nil, 1.2 }, { 'r_lean_antic_nfs360shuvit', 0.3, 'lean' } },
    brake       = { { 'r_brake_n_n_0_into', 0.2 }, { 'r_brake_n_n_0_cyc', 0.2, 'loop' } },
    manual_tail = { { 'm_idle_n_0_cyc', 0.3, 'loop' } },
    -- (Manual.NoseManual: "B_NOSE_MANUAL_INTO time=0.1", "B_NOSE_MANUAL time=0.3", "B_NOSE_MANUAL_OUT time=0.1")
    manual_nose = { { 'm_noseidle_n_0_into', 0.1 }, { 'm_noseidle_n_0_cyc', 0.3, 'loop' } },
    air         = { { 'ia_idle_n_n_0_cyc', 0.2, 'loop' } },
    -- the legs reaching for the ground before the board comes down. In Skate 3 the pose in the air is a blend
    -- driven by how far the board is from the body (air.xml: ControlAirLegExtension, B_AIR_CYC over "disttocog"):
    -- tucked at the top, legs out to meet the ground. Its clips: the tucked idle above (the deck 0.78 m under the
    -- hips) and this one (1.08 m, which is where every landing clip starts).
    air_extend  = { { 'ia_extend_lo_n_0_cyc', 0.2, 'loop' } },
    -- ... and the same two with the board upside down under the feet (air.xml "InAirDark", B_DS_IDLE_N_N_CYC)
    dark        = { { 'ia_ds_idle_n_n_0_cyc', 0.2, 'loop' } },
    dark_extend = { { 'ia_ds_idle_lo_n_0_cyc', 0.2, 'loop' } },
    -- a foot off the board in the air (air.xml "OneFootOllie"): the push button of that foot. Front / back are the
    -- rider's own; high = legs pulled up, low = reaching for the ground (the game blends the two by how far the
    -- board is from the body)
    onefoot_front    = { { '1ft_air_ollie_n_front_high_into', 0.1 }, { '1ft_air_ollie_n_front_high_cyc', 0.1, 'loop' } },
    onefoot_back     = { { '1ft_air_ollie_n_back_high_into', 0.1 }, { '1ft_air_ollie_n_back_high_cyc', 0.1, 'loop' } },
    onefoot_front_lo = { { '1ft_air_ollie_n_front_low_into', 0.1 }, { '1ft_air_ollie_n_front_low_cyc', 0.1, 'loop' } },
    onefoot_back_lo  = { { '1ft_air_ollie_n_back_low_into', 0.1 }, { '1ft_air_ollie_n_back_low_cyc', 0.1, 'loop' } },
    -- (grab_fs, grab_bs ... : the grabs in the air are added below, from the GRAB table)
    -- ground grabs (onground.xml "Grabbing", GroundGrabs/*.xml): a hand on the board while rolling, crouched down
    -- to it. Same hands as in the air: back hand = FS, front hand = BS, both = double.
    ggrab_fs  = { { tri('gr_crouch2grablft_n_fs_0_into', 'gr_crouch2grab_n_fs_0_into', 'gr_crouch2grabrit_n_fs_0_into'), 0.1 },
                  { tri('gr_ground_fs_carve_l_cyc', 'gr_ground_n_fs_0_cyc', 'gr_ground_fs_carve_r_cyc'), 0.2, 'turn' } },
    ggrab_bs  = { { tri('gr_crouch2grablft_n_bs_0_into', 'gr_crouch2grab_n_bs_0_into', 'gr_crouch2grabrit_n_bs_0_into'), 0.1 },
                  { tri('gr_ground_bs_carve_l_cyc', 'gr_ground_n_bs_0_cyc', 'gr_ground_bs_carve_r_cyc'), 0.2, 'turn' } },
    ggrab_dbl = { { tri('gr_crouch2grablft_n_dbl_0_into', 'gr_crouch2grab_n_dbl_0_into', 'gr_crouch2grabrit_n_dbl_0_into'), 0.1 },
                  { tri('gr_ground_n_dbl_carve_l_cyc', 'gr_ground_n_dbl_0_cyc', 'gr_ground_n_dbl_carve_r_cyc'), 0.2, 'turn' } },
    -- the coffin (coffin.xml, GroundGrabs/Coffin.xml): out of the double grab the rider lies back on the board
    coffin    = { { 'gr_ground_n_coffin_0_into', 0.1 },
                  { tri('gr_ground_n_coffin_left_cyc', 'gr_ground_n_coffin_0_cyc', 'gr_ground_n_coffin_right_cyc'), 0.2, 'turn' } },
    -- the hippy jump: the crouch (both push buttons held), then for each height the jump and its tucked cycle
    hippy_antic = { { 't_hippyjump_high_n_0_antic', 0.1 }, { 't_hippyjump_antic_cyc', 0.1, 'loop' } },
    hippy_mini = { { 't_hippyjump_mini_n_0_into', 0.1, nil, 1.1 }, { 't_hippyjump_mini_n_0_cyc', 0.1, 'loop' } },
    hippy_low  = { { 't_hippyjump_low_n_0_into', 0.1, nil, 1.1 }, { 't_hippyjump_low_n_0_cyc', 0.1, 'loop' } },
    hippy_high = { { 't_hippyjump_high_n_0_into', 0.1, nil, 1.1 }, { 't_hippyjump_high_n_0_cyc', 0.1, 'loop' } },
    -- a revert (revert.xml): the board is slid round half a turn on the ground; the turning itself is the ride's
    revert_fs = { { 'r_turn_180slide_fs_n_0_n', 0.2 } }, revert_bs = { { 'r_turn_180slide_bs_n_0_n', 0.2 } },
    -- landings (Landing.xml): straight = one of three at random, by impact; "nice" after a spin; "sketchy" when the
    -- board came down off line; with a hand still on the board
    land_1 = { { 'l_hcom_limp_1', 0.15 } }, land_2 = { { 'l_hcom_limp_2', 0.15 } }, land_3 = { { 'l_hcom_limp_3', 0.15 } },
    land_hard_1 = { { 'l_hcom_himp_1', 0.15 } }, land_hard_2 = { { 'l_hcom_himp_2', 0.15 } },
    land_hard_3 = { { 'l_hcom_himp_3', 0.15 } },
    land_nice_fs = { { 'l_nice_fs_hcom_hsp_limp', 0.15 } }, land_nice_bs = { { 'l_nice_bs_hcom_hsp_limp', 0.15 } },
    land_nice_fs_hard = { { 'l_nice_fs_hcom_hsp_himp', 0.15 } }, land_nice_bs_hard = { { 'l_nice_bs_hcom_hsp_himp', 0.15 } },
    land_sketchy_fs = { { 'l_sketch_fs_hcom_limp1', 0.15 } }, land_sketchy_bs = { { 'l_sketch_bs_hcom_limp1', 0.15 } },
    land_grab_fs = { { 'l_fsgrab', 0.1 } }, land_grab_bs = { { 'l_bsgrab', 0.1 } }, land_grab_dbl = { { 'l_dblgrab', 0.1 } },
    -- riding fakie for a moment: the skater turns round on the board and rides switch (ground.xml, B_SWITCH)
    switch      = { { 'r_switch_ride_n_0_n', 0.15 } },
}
-- push: into > contact > recover (> contact ...) > out. Skate 3 blends four versions by speed and strength; we
-- play the nearest one. Mongo = pushing with the front foot.
local PUSH = {
    slow       = { 'r_pushlsp_lstr_n_0_into', 'r_pushlsp_lstr_n_0_cyc1', 'r_pushlsp_lstr_n_0_cyc2', 'r_push_l_n_out_front' },
    fast       = { 'r_pushhsp_lstr_n_0_into', 'r_pushhsp_lstr_n_0_cyc1', 'r_pushhsp_lstr_n_0_cyc2', 'r_push_h_n_out_front' },
    slow_mongo = { 'r_pushlsp_lstr_mongo_0_into', 'r_pushlsp_lstr_mongo_0_cyc1', 'r_pushlsp_lstr_mongo_0_cyc2',
                   'r_push_l_m_n_out_front' },
    fast_mongo = { 'r_pushhsp_lstr_mongo_0_into', 'r_pushhsp_lstr_mongo_0_cyc1', 'r_pushhsp_lstr_mongo_0_cyc2',
                   'r_push_h_m_n_out_front' },
}
local function pushChain(kind)
    local p = PUSH[kind] or PUSH.slow
    return { { p[1], 0.3 }, { p[2], 0.05 }, { p[3], 0.05 }, { p[4], 0.2 } }
end
-- played first when one of these states ends
local EXIT = {
    stand = { 'r_stand_idle2_n_0_out', 0.2 }, brake = { 'r_brake_n_n_0_out', 0.2 },
    antic_ollie = { 'r_antic_ollie_n_0_out', 0.15 }, antic_shuv = { 'r_antic_ollie_n_0_out', 0.15 },
    antic_fsshuv = { 'r_antic_ollie_n_0_out', 0.15 }, antic_nollie = { 'r_antic_nollie_n_0_out', 0.15 },
    antic_nshuv = { 'r_antic_nollie_n_0_out', 0.15 }, antic_nfsshuv = { 'r_antic_nollie_n_0_out', 0.15 },
    stand_from_brake = { 'r_stand_idle2_n_0_out', 0.2 },
    manual_nose = { 'm_noseidle_n_0_out', 0.1 },
    -- the foot back on the board (OneFootOllie "Out": playBackSpeed 1.2)
    onefoot_front = { '1ft_air_ollie_n_front_high_out', 0.1, nil, 1.2 },
    onefoot_back = { '1ft_air_ollie_n_back_high_out', 0.1, nil, 1.2 },
    onefoot_front_lo = { '1ft_air_ollie_n_front_low_out', 0.1, nil, 1.2 },
    onefoot_back_lo = { '1ft_air_ollie_n_back_low_out', 0.1, nil, 1.2 },
    -- letting go of a ground grab (FSGrabOut: B_FSGRAB_OUT, blend 0.05)
    ggrab_fs  = { tri('gr_ground_fs_carve_l_out', 'gr_ground_n_fs_0_out', 'gr_ground_fs_carve_r_out'), 0.05 },
    ggrab_bs  = { tri('gr_ground_bs_carve_l_out', 'gr_ground_n_bs_0_out', 'gr_ground_bs_carve_r_out'), 0.05 },
    ggrab_dbl = { tri('gr_ground_dbl_carve_l_out', 'gr_ground_n_dbl_0_out', 'gr_ground_dbl_carve_r_out'), 0.05 },
    -- out of the coffin with nothing held: the rider sits up as into the FS grab and rides on (Coffin.xml: CoffinToFS
    -- is the way out when no other applies)
    coffin    = { 'gr_ground_n_coffin_fsgrab_out', 0.1 },
}
for kind, d in pairs(GRAB) do
    CHAIN['grab_' .. kind] = { { d.clip .. '_into', 0.1, nil, d.rate }, { d.clip .. '_cyc', 0.1, 'loop' } }
    EXIT['grab_' .. kind] = { d.clip .. '_out', 0.1, nil, d.outRate }
end
-- The clips of a grab's variant that is gone into and come out of: into, cycle, out (and how fast the out plays).
local function variantClips(e, super)
    if super then return e[1] .. '_0_into', e[1] .. '_0_cyc', e[1] .. '_0_out', 1.0, 0.2 end
    -- (the rocket air's way out is played as it is: "S_GR_NOSEGRAB_ROCKETAIR_N_0_OUT time=0.1", no playBackSpeed)
    if e[2] == 'rocketair' then return e[1] .. '_0_into', e[1] .. '_0_cyc', e[1] .. '_0_out', 1.0, 0.1 end
    return e[1] .. '_0_into', e[1] .. '_0_cyc', e[1] .. '_0_out', 1.2, 0.1
end
-- from one ground grab to another (BLEND_FS2BS_TR ...: a hand comes off, the other goes on), blend 0.1
local GGRAB_TR = {}
for _, pair in ipairs({ 'fs2bs', 'fs2dbl', 'bs2fs', 'bs2dbl', 'dbl2fs', 'dbl2bs' }) do
    GGRAB_TR[pair] = { tri(('gr_grablft_n_%s_0_tr'):format(pair), ('gr_grab_n_%s_0_tr'):format(pair),
                           ('gr_grabrit_n_%s_0_tr'):format(pair)), 0.1 }
end
-- sitting up out of the coffin into the ground grab that is still held (Coffin.xml: CoffinToDBL / ToBS / ToFS)
local COFFIN_OUT = {
    ggrab_dbl = { 'gr_ground_n_coffin_2hgrab_out', 0.1 }, ggrab_bs = { 'gr_ground_n_coffin_bsgrab_out', 0.1 },
    ggrab_fs = { 'gr_ground_n_coffin_fsgrab_out', 0.1 },
}
-- Skitching: holding on to the back of a car (ground.xml "EnterSkitching" / "Skitching"). k = { hand = 'left' |
-- 'right' (the one hand that still has the car, at an end of it; nil = both), high (a hold at chest height, not
-- down at a bumper), shimmy = -1 .. 1 (moving along the car, + = to the right), fast (the car was closed on fast) }.
-- The clip that is held, and the blend into it: both hands (SKITCHING2H, 0.4), hand over hand along the car
-- (SkitchShimmyingBehaviour; EndShimmy blends back in 0.2), one hand (SKITCHING1HFRONT / BACK, 0.4). As authored
-- (goofy) the front hand is the right one (Skitch1HandFS: WorldGrabRightHand); the mirrored copies swap them.
local function skitchClip(k)
    local hi = k.high and '_hi' or ''
    if k.hand then
        return 'skch_1h_idle_' .. (((k.hand == 'right') ~= S3.mirror) and 'fronthand' or 'backhand') .. hi, 0.4
    elseif k.shimmy then
        local a = math.abs(k.shimmy)
        return ('skch_2h_shimmy_%s_%s_%s'):format(((k.shimmy > 0) ~= S3.mirror) and 'r' or 'l', k.high and 'hi' or 'lo',
            a > 0.66 and 'fast' or (a > 0.33 and 'med' or 'slow')), 0.2
    end
    return 'skch_2h_idle' .. hi, 0.2
end
-- Reaching for the car and being taken along by it (EnterSkitching.Into: B_SKCH_2H_INTO_REACH, then Skitch2Hand.
-- Absorb: B_SKCH_2H_INTO_ABSORB when the car's speed pulls on the arms, both blended in over 0.1 s). The game has
-- a quick and a slow version of each. absorb = nil | 'slow' | 'fast'.
local function skitchInto(fast, absorb)
    local chain = { { ('skch_2h_into_%s_reach'):format(fast and 'fast' or 'slow'), 0.1 } }
    if absorb then chain[2] = { ('skch_2h_into_%s_absorb'):format(absorb), 0.1 } end
    return chain
end

-- Off the board (Skate 3's OffBoard.abin; offboard.xml, mount.xml, dismount.xml). The names are built from: who
-- (br = board in the hand, nb = no board), the gait (walk / run / sprint) and, for a stop or a mount out of a gait,
-- which quarter of its stride the cycle is in (0, 25, 50, 75: the game has a clip for each).
local OFF = {
    stand = '%s_stand_0_cyc', cycle = '%s_%s_fwd_cyc', start = '%s_stand_0_into_%s_fwd',
    stop = '%s_%s_fwd_%d_into_stand_0',
    mountStand = 'br_stand_0_into_mount', mount = 'br_%s_fwd_%d_into_mount',
    -- off the board on the ground, by speed (dismount.xml: under 1 m/s, under 8, under 15)
    dismount = { stand = 'br_dismount_hi_into_stand_0', run = 'br_dismount_hi_into_run_fwd',
                 fast = 'br_dismount_fast_hi_into_run_fwd' },
    -- off the board in the air: the board is kicked away, or comes along in the hand that was grabbing it
    kickout = 'br_kickout_hi_into_nb_air',
    airGrab = { fs = 'br_dismount_fs_into_br_air', bs = 'br_dismount_bs_into_br_air', dbl = 'br_dismount_dbl_into_br_air',
                mute = 'br_dismount_mute_into_br_air', stale = 'br_dismount_stale_into_br_air' },
    -- landing on the feet: a small or a big drop, into a stand or into a run
    land = { stand = '%s_land_%s_dn_0_into_stand', run = { sml = '%s_land_sml_dn_25_into_run_fwd',
                                                           big = '%s_land_big_dn_0_into_run_fwd' } },
}
local GAITS, QUARTERS = { 'walk', 'run', 'sprint' }, { 0, 25, 50, 75 }

-- one-shot chains that run to their end unless something more important interrupts ('switch' holds its last
-- frame until the ride has turned the rider round, see S3.setMirrored)
local ONESHOT = { push = true, land = true, pop = true, trick = true, revert = true }

local function call(name, ...)
    local ok, result = pcall(function(...) return exports[RES][name](exports[RES], ...) end, ...)
    if ok then return result end
    id = nil -- skate3_assets went away: drop back to the stock poses
end

-- Mirrored riders (regular stance, or goofy riding switch) play the left-right mirrored copy of a clip
-- (<clip>_mir), when the asset build has one. Gestures only move the arms and are never mirrored.
function S3.mirrored() return S3.mirror end

local function clipName(clip)
    if not S3.mirror or clip:find('^b_gstr_') then return clip end
    if names[clip] == nil then names[clip] = call('HasClip', clip .. '_mir') and (clip .. '_mir') or clip end
    return names[clip]
end

local function length(clip)
    if not lengths[clip] then lengths[clip] = call('ClipLength', clip) or 0.0 end
    return lengths[clip]
end

local function hasClip(clip)
    if names['?' .. clip] == nil then names['?' .. clip] = call('HasClip', clip) and true or false end
    return names['?' .. clip]
end

-- Every clip this file can ask for (to check a skate3_assets build against).
function S3.clipNames()
    local list, seen = {}, {}
    local function add(c)
        if type(c) == 'table' then -- the three versions of a clip (see tri)
            add(c.l); add(c.c); add(c.r)
        elseif not seen[c] then
            seen[c], list[#list + 1] = true, c
        end
    end
    local function addChain(chain)
        for _, s in ipairs(chain) do
            add(s[1])
            if s[3] == 'lean' then
                for k = 0, LEAN_STEPS - 1 do add(s[1] .. '_s' .. k) end
            end
        end
    end
    for _, chain in pairs(CHAIN) do addChain(chain) end
    for kind in pairs(PUSH) do addChain(pushChain(kind)) end
    for _, s in pairs(EXIT) do add(s[1]) end
    for _, s in pairs(GGRAB_TR) do add(s[1]) end
    for _, s in pairs(COFFIN_OUT) do add(s[1]) end
    for _, c in pairs(GRAB_TR) do add(c) end
    for _, fast in ipairs({ false, true }) do addChain(skitchInto(fast, fast and 'fast' or 'slow')) end
    for _, who in ipairs({ 'br', 'nb' }) do
        add(OFF.stand:format(who))
        for _, gait in ipairs(GAITS) do
            add(OFF.cycle:format(who, gait)); add(OFF.start:format(who, gait))
            for _, quarter in ipairs(QUARTERS) do add(OFF.stop:format(who, gait, quarter)) end
        end
        for _, size in ipairs({ 'sml', 'big' }) do
            add(OFF.land.stand:format(who, size)); add(OFF.land.run[size]:format(who))
        end
    end
    add(OFF.mountStand); add(OFF.kickout)
    for _, gait in ipairs(GAITS) do
        for _, quarter in ipairs(QUARTERS) do add(OFF.mount:format(gait, quarter)) end
    end
    for _, c in pairs(OFF.dismount) do add(c) end
    for _, c in pairs(OFF.airGrab) do add(c) end
    for _, high in ipairs({ false, true }) do
        add((skitchClip({ high = high })))
        for _, hand in ipairs({ 'left', 'right' }) do add((skitchClip({ high = high, hand = hand }))) end
        for _, v in ipairs({ 0.2, 0.5, 1.0 }) do
            add((skitchClip({ high = high, shimmy = v })))
            add((skitchClip({ high = high, shimmy = -v })))
        end
    end
    for _, d in pairs(PLANT) do
        for _, class in ipairs(d.classes) do
            for _, part in ipairs({ 'g', 'f', 'l', 'a' }) do
                if part ~= 'g' or not d.noGround then add(d.clip:format(class, part)) end
            end
        end
    end
    for _, d in pairs(GRAB) do
        for _, e in pairs(d.tweak or {}) do add(e[1]) end
        for _, e in pairs(d.foot or {}) do
            local a, b, c = variantClips(e)
            add(a); add(b); add(c)
        end
        for _, name in ipairs({ 'nofoot', 'airwalk', 'rocket', 'super' }) do
            if d[name] then
                local a, b, c = variantClips(d[name])
                add(a); add(b); add(c)
                if d[name].toSuper then add(d[name].toSuper); add(d[name].fromSuper) end
            end
        end
        if d.flip then add(d.flip[1] .. '_into_0_n'); add(d.flip[1] .. '_out_n_grab'); add(d.flip[1] .. '_out_n_high') end
        if d.var then add(d.var[1] .. '_into'); add(d.var[1] .. '_out_grab'); add(d.var[1] .. '_out_high') end
        if d.shuv then add(d.shuv[1]) end
    end
    for g, d in pairs(GRIND) do
        for _, side in ipairs({ 'fs', 'bs' }) do
            for _, fakie in ipairs({ false, true }) do
                for _, low in ipairs({ false, true }) do
                    for _, bal in ipairs({ 'l', '0', 'r' }) do
                        if not fakie or d.fakie then add(grindClip(g, side, fakie, low, bal)) end
                        if d.rail then add(grindClip(g, side, false, low, bal, true)) end
                        if d.dark then
                            for _, e in ipairs({ DARK_SLIDE_STRAIGHT, DARK_SLIDE_OUT.Kickflip, DARK_SLIDE_OUT.Heelflip }) do
                                add(('t_dslide_%s_%s_%s_%s'):format(side, low and 'low' or 'hi', bal, e[1]))
                            end
                        end
                    end
                end
            end
        end
    end
    for g, d in pairs(GRIND) do
        for hand in pairs(d.grab or {}) do
            for _, side in ipairs({ 'fs', 'bs' }) do
                for _, fakie in ipairs({ false, true }) do
                    for _, onRail in ipairs({ false, true }) do
                        local c = grindGrabClip(g, hand, side, fakie and d.fakie ~= nil, onRail)
                        if c then add(c .. '_into'); add(c .. '_cyc'); add(c .. '_out') end
                    end
                end
            end
        end
    end
    for _, g in ipairs(Config.Gestures or {}) do
        for _, part in ipairs({ 'into', 'cyc', 'out' }) do add(('b_gstr_%s_both_%s'):format(g, part)) end
    end
    for name, t in pairs(TRICK) do
        for _, isHigh in ipairs({ true, false }) do
            local g, a = trickClips(name, isHigh)
            add(g); add(a)
            local hl = isHigh and 'hi' or 'low'
            local m = t.multi
            if m then
                for k = 1, 4 do
                    if k < 4 then add(m.cyc:format(hl, k)); add(m.out:format(hl, k)) else add(m.out4:format(hl)) end
                    add(m.uflip:format(hl, k)); add(m.dcatch:format(hl, k))
                end
            end
            if t.uflip then add(t.uflip:format(hl)) end
            if t.dcatch then add(t.dcatch:format(isHigh and 'hi' or (t.dlow or 'low'))) end
        end
    end
    for _, l in pairs(LATE) do add(lateClip(l, true)); add(lateClip(l, false)) end
    for _, d in pairs(DARK_OUT) do add(d.clip:format('hi')); add(d.clip:format('low')) end
    add(DARK_LATE:format('hi')); add(DARK_LATE:format('low'))
    return list
end

function S3.available()
    return Config.UseSkate3Anims and GetResourceState(RES) == 'started'
end

function S3.active() return id ~= nil end

-- True once skate3_assets has every clip dictionary in memory (it loads them when it starts).
function S3.ready()
    local ok, ready = pcall(function() return exports[RES]:Ready() end)
    return not ok or ready == true -- an older build without the export: don't wait for it
end

-- Skate 3's Flick-It patterns ({ ground = {...}, air = {...} }), when the asset build has them.
function S3.patterns() return patterns end

-- Skate 3's own tuning numbers (see tuning.lua), when the asset build has them; nil otherwise.
function S3.tuning()
    local ok, t = pcall(function() return exports[RES]:Tuning() end)
    return ok and type(t) == 'table' and t or nil -- an older build without the export: the numbers in config.lua
end

-- The trick a Flick-It gesture gives this rider: the gesture's own trick, or its mirror twin for a mirrored rider.
-- Returns the trick key, its on-screen name and whether it pops off the nose; nil for an unknown gesture.
function S3.trick(pattern)
    local t = TRICK[pattern]
    if not t then return nil end
    if S3.mirror and t.swap then pattern, t = t.swap, TRICK[t.swap] end
    return pattern, t.label, t.nose == true
end

function S3.trickLabel(name) return TRICK[name] and TRICK[name].label or name end

function S3.trickNames()
    local list = {}
    for name in pairs(TRICK) do list[#list + 1] = name end
    table.sort(list)
    return list
end

function S3.grindLabel(name) return GRIND[name] and GRIND[name].label or name end

local function play(clip, blend, loop)
    local c = clipName(clip)
    local ok = call('Play', id, c, { blend = blend, loop = loop })
    if ok then S3.clip, S3.seq = c, S3.seq + 1 end
    return ok, c
end

-- The step clip index (0 .. LEAN_STEPS-1) for a lean of -1 .. 1.
local function leanStep(v) return math.floor((math.max(-1.0, math.min(1.0, v)) + 1.0) * 0.5 * (LEAN_STEPS - 1) + 0.5) end

-- Which of a clip's three versions (see tri) the steering asks for: 'l' | 'c' | 'r', with some hysteresis around
-- the one showing. `lean` already runs the authored clips' way (see S3.update).
local function turnSide(cur)
    local lim = cur == 'c' and 0.45 or 0.3
    if lean < -lim then return 'l' elseif lean > lim then return 'r' end
    return 'c'
end

local function playStep()
    local s = steps[index]
    local blend = cutNext and 0.0 or s[2]
    stepT, live, turning, cutNext = 0.0, nil, nil, false
    local base = s[1]
    if type(base) == 'table' then
        local side = turnSide('c')
        if s[3] == 'turn' then turning = { set = base, side = side } end
        base = base[side]
    end
    if s[3] == 'lean' and hasClip(clipName(base .. '_s0')) then
        -- the lean as static poses the game cross-fades between (these sync to other players; a scrub doesn't)
        local k = leanStep(lean)
        live = { base = base, k = k }
        stepLen = 0.0
        if not play(base .. '_s' .. k, blend, true) then live = nil end
        return
    end
    local clip = clipName(base)
    local rate = s[4] or 1.0
    stepLen = length(clip) / rate
    local ok = call('Play', id, clip, { blend = blend, loop = s[3] == 'loop' or s[3] == 'turn', scrub = s[3] == 'lean',
                                       phase = 0.5, rate = s[4] })
    if ok then S3.clip, S3.seq = clip, S3.seq + 1 else stepLen = 0.0 end -- missing or not loaded yet: skip it
end

local function run(newKey, chain, exitClip)
    key, steps, index, gvar, fingering = newKey, {}, 1, nil, false
    if exitClip then steps[1] = exitClip end
    for _, s in ipairs(chain) do steps[#steps + 1] = s end
    playStep()
end

-- Start posing `ped` (with `board` under the feet). mirrored: see the top of this file.
-- keep = the rider is already being posed (coming back onto the board out of Skate 3's off-board mode): carry on with
-- the same one, so nothing is dropped between the jump onto the board and the ride.
function S3.start(ped, board, mirrored, keep)
    if not (keep and id) then id = call('StartRide', ped, board or false) end
    key, steps, lean, S3.lift, live, grindKey, gesture, turning = nil, nil, 0.0, 0.0, nil, nil, nil, nil
    lengths, names, pushKind, cutNext, prog, darkOn, grindGrab, slideOut = {}, {}, nil, false, nil, false, nil, nil
    planting, afterPlant = nil, false
    S3.clip, S3.upper, S3.mirror = nil, nil, mirrored == true
    if id then
        patterns = Config.UseSkate3Flick and call('FlickPatterns') or nil
        -- an older skate3_assets build may lack clips this version plays
        local missing = {}
        for _, clip in ipairs(S3.clipNames()) do
            if not call('HasClip', clip) then missing[#missing + 1] = clip end
            if not clip:find('^b_gstr_') and not call('HasClip', clip .. '_mir') then missing[#missing + 1] = clip .. '_mir' end
        end
        if #missing > 0 then
            print(('^3[skateboard] skate3_assets is missing %d clips (rebuild it with skate3-sp/tools): %s^7')
                :format(#missing, table.concat(missing, ' ', 1, math.min(#missing, 8))))
        end
    end
    return id ~= nil
end

function S3.stop()
    if id then call('StopRide', id, true) end
    id, key, steps, gesture, live, grindKey, turning, prog, darkOn = nil, nil, nil, nil, nil, nil, nil, nil, false
    S3.lift, S3.clip, S3.upper = 0.0, nil, nil
end

-- ------------------------------------------------------------------ off the board
-- The ride (client.lua) runs Skate 3's off-board rules; these give it the clips. what = 'stand' | 'cycle' | 'start' |
-- 'stop' | 'mount' | 'dismount' | 'kickout' | 'airGrab' | 'land'.
function S3.offClip(what, holding, a, b)
    local who = holding and 'br' or 'nb'
    if what == 'stand' then return OFF.stand:format(who) end
    if what == 'cycle' or what == 'start' then return OFF[what]:format(who, a) end
    if what == 'stop' then return OFF.stop:format(who, a, b) end
    if what == 'mount' then return a and OFF.mount:format(a, b) or OFF.mountStand end
    if what == 'dismount' then return OFF.dismount[a] end
    if what == 'kickout' then return OFF.kickout end
    if what == 'airGrab' then return OFF.airGrab[a] end
    if what == 'land' then return a == 'stand' and OFF.land.stand:format(who, b) or OFF.land.run[b]:format(who) end
end

-- Play one of them (the ride's own states are dropped: the body is the off-board mode's now). Returns its length.
function S3.offPlay(clip, blend, loop)
    if not id then return 0.0 end
    if gesture then -- (a gesture in progress ends: the arms are the off-board clips' now)
        gesture, S3.upper = nil, nil
        call('StopUpper', id)
    end
    key, steps, live, grindKey, turning, prog, darkOn = nil, nil, nil, nil, nil, nil, false
    play(clip, blend, loop)
    return length(clipName(clip))
end

-- Metres the playing clip has carried the rider forward since last asked; where in the clip it is (0 .. 1).
function S3.offTravel() return id and call('Travel', id) or 0.0 end
function S3.offPhase() return id and call('Phase', id) or 0.0 end

-- Put the rider on the ground at x, y, z facing `heading`; holding = the board is in the hand (else it is left alone).
function S3.offDrive(x, y, z, heading, holding)
    if id then call('Drive', id, x, y, z, heading, 0.0, true, false, false, false, false, holding and true or 'free') end
end

-- The rider now plays the other set of clips: the stance switch has played and the ride has turned the rider round
-- by 180 degrees. The switch clip ends in the other set's riding pose seen from behind, so the next clip starts
-- without a cross-fade (a fade would blend through the old pose pointing the wrong way).
function S3.setMirrored(mirrored)
    if S3.mirror == (mirrored == true) then
        if key == 'switch' then key, cutNext = nil, true end -- (the turn has been played: it is not the pose to stay in)
        return
    end
    S3.mirror, names, lengths = mirrored == true, {}, {}
    key, live, grindKey, turning, cutNext = nil, nil, nil, nil, true -- what is showing belongs to the other set: start the state again
end

-- Skate 3's own sounds, when the asset build has them: { base = address of the folder, sounds = { name =
-- { files = {...}, gain, loop, rate } } } (see html/sound.js). nil otherwise.
function S3.sounds()
    local ok, t = pcall(function() return exports[RES]:Sounds() end)
    return ok and type(t) == 'table' and t or nil
end

-- How often skate3_assets had to restart a clip the game dropped (0 when all is well).
function S3.replays() return id and call('Replays', id) or 0 end

-- What the game is really doing with the rider this frame, from skate3_assets (the numbers /s3debug shows):
-- { clip, dict, playing, phase, oneFoot, blending, feet = { sideways, forward, up } (metres, real foot bones against
-- where the board was put), replays, lift, grounded }. nil when not on Skate 3's clips or with an older asset build.
function S3.probe()
    if not id then return nil end
    local ok, p = pcall(function() return exports[RES]:Probe(id) end)
    return ok and p or nil
end

-- ------------------------------------------------------------------ gestures (Skate 3's B_GSTR clips)

local GESTURE_PART = { 'into', 'cyc', 'out' }

local function gestureStep(step)
    gesture.step, gesture.t = step, 0.0
    local clip = ('b_gstr_%s_both_%s'):format(gesture.name, GESTURE_PART[step])
    gesture.len = step == 2 and Config.GestureTime or length(clip)
    if call('PlayUpper', id, clip, step == 2) then S3.upper = clip else gesture.len = 0.0 end
end

local function stopGesture()
    if not gesture then return end
    gesture, S3.upper = nil, nil
    if id then call('StopUpper', id) end
end

-- Tricks and grabs need the arms.
local function armsBusy(k)
    return k == 'pop' or k == 'trick' or k == 'coffin' or k == 'skitch' or (k ~= nil and k:find('^g?grab_') ~= nil)
end

-- The next gesture from Config.Gestures, layered over whatever the body is doing. False when it can't play now.
function S3.gesture()
    local list = Config.Gestures
    if not id or armsBusy(key) or not list or #list == 0 then return false end
    gestureIndex = gestureIndex % #list + 1
    gesture = { name = list[gestureIndex] }
    gestureStep(1)
    return id ~= nil
end

-- ------------------------------------------------------------------ pushing

-- Where the push is: 'into' | 'contact' (the foot is on the ground: this is when the board gains speed) |
-- 'recover' | 'out', or nil when not pushing.
local PUSH_PHASE = { 'into', 'contact', 'recover', 'out' }
function S3.pushPhase()
    if key ~= 'push' then return nil end
    return PUSH_PHASE[index]
end

-- How long the foot takes to come off the board and down for a push (Push.xml "PushStart"): seconds.
function S3.pushStartTime()
    local p = PUSH[pushKind] or PUSH.slow
    return length(clipName(p[1]))
end

-- How long the foot is on the ground in one push (seconds).
function S3.pushContactTime()
    local p = PUSH[pushKind] or PUSH.slow
    return length(clipName(p[2]))
end

-- ------------------------------------------------------------------ tricks

-- Start a trick's takeoff: the high version for a strong pop, the low one for a weak pop. from = 'grind' blends
-- out of the grind pose more slowly, as Skate 3 does (T_Trick.xml FromGrind). Returns how long the takeoff lasts;
-- the caller leaves the ground after that.
function S3.pop(name, isHigh, from)
    high = isHigh
    stopGesture()
    slideOut = nil
    if from == 'grind' and grindKey and GRIND[grindKey.name] and GRIND[grindKey.name].dark then
        -- off a darkslide: one clip from the rail into the air, the board coming the right way up in it
        local e = DARK_SLIDE_OUT[name] or DARK_SLIDE_STRAIGHT
        local k = grindKey
        slideOut = { key = 'darkslideout_' .. k.side .. e[2], label = e[3] }
        run('pop', { { ('t_dslide_%s_%s_%s_%s'):format(k.side, k.low and 'low' or 'hi', k.bal, e[1]), 0.05 } })
        return math.min(stepLen, 0.1)
    end
    run('pop', { { trickClips(name, high), from == 'grind' and 0.2 or 0.05 } })
    return stepLen
end

-- A foot plant off the ground (see PLANT): name = 'fsboneless' | 'bsboneless' | 'fsfastplant' | 'bsfastplant' |
-- 'nocomply', speed = how fast the board is rolling. Plays the foot going down, planted and the board lifted;
-- returns how long that takes (the caller leaves the ground then) and the trick's on-screen name. nil when it
-- cannot start.
function S3.plant(name, speed)
    local d = PLANT[name]
    if not id or not d then return nil end
    local v = math.abs(speed)
    local class
    if d.noGround then
        class = v < 2.5 and 'slow' or (v < 5.0 and 'med' or 'fast')
    else
        class = v < 0.5 and 'stop' or (v < Config.S3FastPush and 'slow' or 'fast')
    end
    stopGesture()
    slideOut, planting = nil, { d = d, class = class }
    local chain, total = {}, 0.0
    for i, part in ipairs(d.noGround and { 'f', 'l' } or { 'g', 'f', 'l' }) do
        local clip = d.clip:format(class, part)
        chain[i] = { clip, i == 1 and 0.05 or 0.1 }
        total = total + length(clipName(clip))
    end
    run('pop', chain)
    return total, d.label
end

-- The hippy jump's heights: 'mini' | 'low' | 'high' for a crouch held `t` seconds, and when in the jump's clip the
-- feet leave the board (the legs at their longest), seconds from its start.
function S3.hippy(t)
    local h = t < HIPPY_CROUCH.mini and 'mini' or (t < HIPPY_CROUCH.low and 'low' or 'high')
    local clip = clipName(CHAIN['hippy_' .. h][1][1])
    return h, (call('DeepestFrame', clip) or length(clip) * 0.5) / 1.1
end

-- Slide the board round half a turn on the ground. side = 'fs' | 'bs'. Returns how long its clip is.
function S3.revert(side)
    if not id then return 0.0 end
    stopGesture()
    run('revert', CHAIN['revert_' .. (side == 'bs' and 'bs' or 'fs')])
    return stepLen
end

-- The jump off a darkslide: what it scores as and is called, once S3.pop has started it; nil for any other pop.
function S3.slideOut()
    if not slideOut then return nil end
    return slideOut.key, slideOut.label
end

-- The moment in `clip` where an underflip or a dark catch takes over: where the board lies as it does at the start
-- of the clip made to carry on from there (the game marks that frame with a tag in the clip, "cantranstounderflip";
-- the tags cannot be read, the clips can). Returns { t = seconds into the clip, uflip = clip, dcatch = clip }.
local function window(clip, uflip, dcatch)
    local t = call('MatchFrame', clipName(clip), clipName(dcatch or uflip))
    if not t then return nil end
    return { t = t, uflip = uflip, dcatch = dcatch }
end

-- Go on with this clip of the flip.
local function flipPlay(clip, blend)
    steps, index = { { clip, blend } }, 1
    playStep()
end

-- The board has left the ground: play the in-air part of the trick.
function S3.launch(name)
    if planting then
        -- off the planted foot: in the air the board comes back under the feet
        local p = planting
        planting, flipping, prog, darkOn, afterPlant = nil, true, nil, false, true
        run('trick', { { p.d.clip:format(p.class, 'a'), 0.05 } })
        return
    end
    afterPlant = false
    if slideOut and key == 'pop' then
        -- the clip off the darkslide carries on through the air; the board is the right way up at its end
        key, flipping, prog, darkOn = 'trick', true, nil, false
        return
    end
    local _, air = trickClips(name, high)
    local t = TRICK[name] or TRICK.Ollie
    flipping = name ~= 'Ollie' and name ~= 'Nollie'
    darkOn = false
    prog = { name = name, t = t, hl = high and 'hi' or 'low', stage = 'in', n = 1 }
    run('trick', { { air, 0.05 } })
    if not id then return end
    local m = t.multi
    if m then
        prog.win = window(air, m.uflip:format(prog.hl, 1), m.dcatch:format(prog.hl, 1))
    elseif t.uflip then
        prog.win = window(air, t.uflip:format(prog.hl), nil)
    elseif t.dcatch then
        prog.win = window(air, nil, t.dcatch:format(high and 'hi' or (t.dlow or 'low')))
    end
end

-- More of a kickflip or a heelflip: the flick is still held (and there is the time), so the board turns on.
local function flipCyc(k)
    local p = prog
    local m = p.t.multi
    local clip = m.cyc:format(p.hl, k)
    p.stage = 'cyc' .. k
    if k == 1 then p.n = 2 else p.count = k + 1 end -- (the second flip counts at once, the others once past the window)
    flipPlay(clip, 0.05)
    if k > 1 then p.win = window(clip, m.uflip:format(p.hl, k), m.dcatch:format(p.hl, k)) end
end

-- ... or it is caught: the catch after k flips.
local function flipOut(k)
    local p = prog
    local m = p.t.multi
    local clip = k < 4 and m.out:format(p.hl, k) or m.out4:format(p.hl)
    p.stage = 'out'
    flipPlay(clip, 0.05)
    if k > 1 then p.win = window(clip, m.uflip:format(p.hl, k), m.dcatch:format(p.hl, k)) end
end

-- The flip in the air, every frame: s.hold = the flick is still held, s.timeToLand = seconds until the board is
-- down, s.uflip = a second flick has come (underflip), s.dcatch = the dark-catch button was pressed.
local function flipStep(s)
    local p = prog
    local w = p.win
    if w and stepT >= w.t then
        p.win = nil
        if s.dcatch and w.dcatch then
            p.dark, p.stage, darkOn = true, 'dark', true
            flipPlay(w.dcatch, 0.1)
            return
        elseif s.uflip and w.uflip then
            p.under, p.stage = true, p.t.multi and 'under' or 'out'
            flipPlay(w.uflip, 0.1)
            return
        end
        if p.count then p.n, p.count = p.count, nil end
    end
    if stepT < stepLen then return end
    local m, st = p.t.multi, p.stage
    if st == 'in' and m then
        -- T_Kickflip.xml: Out1 unless the flick is held and more than 0.525 s of fall are left; Out2 likewise at 0.8 s
        if s.hold and (s.timeToLand or 0.0) > 0.525 then flipCyc(1) else flipOut(1) end
    elseif st == 'cyc1' then
        if s.hold and (s.timeToLand or 0.0) >= 0.8 then flipCyc(2) else flipOut(2) end
    elseif st == 'cyc2' then
        if s.hold then flipCyc(3) else flipOut(3) end
    elseif st == 'cyc3' then
        flipOut(4)
    elseif st == 'under' then
        -- kicked back the other way: the other flip's catch ends it (UnderflipHalfOut: B_HEELFLIP_OUT1 for a kickflip)
        p.stage = 'out'
        flipPlay(TRICK[m.other].multi.out:format(p.hl, 1), 0.05)
    else
        p.stage, key = nil, nil -- caught ('out'), or held upside down ('dark': the dark idle takes over)
    end
end

-- What the flip has come to: { n = how many flips (1 .. 4), under = underflip, dark = caught upside down }, for the
-- name it lands under. nil when the jump was no flip. (A late flip caught dark is a trick of its own, with its own
-- name in the table: it does not make a dark catch of the jump it was done in.)
function S3.flipInfo()
    if not prog or prog.late then return nil end
    return { n = prog.n, under = prog.under == true, dark = prog.dark == true }
end

-- True while the board is upside down under the feet.
function S3.dark() return darkOn end

-- A late flip from one of Skate 3's air gestures (skater_air.pat). Returns its on-screen name and its trick key
-- when it starts. dark = the dark-catch button is held: the board is caught upside down (air.xml "DarkLateflip").
function S3.lateflip(pattern, dark)
    local l = LATE[pattern]
    if not id or not l or (key == 'trick' and flipping) or key == 'pop' or darkOn or (key and key:find('^grab_')) then
        return nil
    end
    local name = pattern
    if S3.mirror and l.swap then name, l = l.swap, LATE[l.swap] end
    stopGesture()
    flipping = true
    if dark then
        prog = { name = 'lateflip', t = {}, hl = high and 'hi' or 'low', stage = 'dark', n = 1, dark = true, late = true }
        darkOn = true
        run('trick', { { DARK_LATE:format(prog.hl), 0.05 } })
        return 'Late Flip Dark Catch', 'lateflip_darkcatch'
    end
    prog = nil
    run('trick', { { lateClip(l, high), 0.05 } })
    return l.label, name
end

-- The board is upside down under the feet: turn it the right way up. pattern = the late-flip gesture flicked
-- (returns the trick's on-screen name and its key), or nil for the quick way out (the dark-catch button pressed
-- again: a kickflip's turn that scores nothing; returns true).
function S3.darkOut(pattern)
    if not id or not darkOn or key == 'trick' then return nil end
    local kind = pattern and DARK_GESTURE[pattern] or (not pattern and 'kickflip' or nil)
    if not kind then return nil end
    local d = DARK_OUT[kind]
    if pattern and S3.mirror then d = DARK_OUT[d.swap] end
    flipping, darkOn, prog = true, false, nil
    run('trick', { { d.clip:format(high and 'hi' or 'low'), 0.05 } })
    if not pattern then return true end
    return d.label, d.key
end

-- The grab in hand, from the body's state: 'fs', 'mute', ... or nil.
local function airGrab(k) return k ~= nil and k:match('^grab_(%a+)$') or nil end

-- A flick of the right stick while grabbing: the board is flipped by hand. Returns the trick's on-screen name, its
-- name in the scoring table and, when the flip ends in another grab, that grab; nil when this grab has no such flip
-- or is not in its cycle yet.
function S3.fingerflip(gesture)
    local kind = airGrab(key)
    local d = kind and GRAB[kind]
    if not id or not d or index < #steps or (gvar and not gvar:find('^tw_')) then return nil end
    local e, what
    if FINGER[gesture] and d.flip then
        e, what = d.flip, 'flip'
    elseif VARIAL[gesture] and (kind == 'fs' or kind == 'bs') then
        -- as authored the FS varial is the one that ends in the other grab; a mirrored rider's is the BS one
        if (VARIAL[gesture] == 'fs') ~= S3.mirror then e, what = d.shuv, 'shuv' else e, what = d.var, 'var' end
    elseif VARIAL[gesture] and (kind == 'mute' or kind == 'stale') then
        e, what = d.shuv, 'shuv'
    elseif TIP_SHUV[gesture] and (kind == 'crail' or kind == 'seatbelt') then
        e, what = d.shuv, 'shuv'
    end
    if not e then return nil end
    stopGesture()
    if what == 'shuv' then
        local to = e[2]
        run('grab_' .. to, { { e[1], 0.05 }, CHAIN['grab_' .. to][2] })
        fingering = true
        return e[4], e[3], to
    end
    local into = what == 'flip' and (e[1] .. '_into_0_n') or (e[1] .. '_into')
    local out = what == 'flip' and (e[1] .. '_out_n_grab') or (e[1] .. '_out_grab')
    run(key, { { into, 0.05 }, { out, 0.05 }, CHAIN[key][2] })
    fingering = true
    return e[3], e[2], nil
end

-- True while a finger flip's clips play.
function S3.fingering() return fingering and airGrab(key) ~= nil and index < #steps end

-- The grab in hand and what the buttons ask for on top of it (s.gvar): change over to it, by the game's clips.
local function grabStep(s)
    if index < #steps then return end -- on the way into the grab or into / out of a variant, or in a finger flip
    fingering = false
    local kind = airGrab(key)
    local d = GRAB[kind]
    local want = s.gvar
    if want and not grabVar(kind, want) then want = nil end
    if want == gvar then return end
    local chain = {}
    local old, oldTweak = grabVar(kind, gvar)
    if old and not oldTweak then
        local _, _, out, rate, blend = variantClips(old, gvar == 'super')
        chain[#chain + 1] = { out, blend, nil, rate }
    end
    local e, tweak = grabVar(kind, want)
    if not want then
        chain[#chain + 1] = { d.clip .. '_cyc', oldTweak and 0.13 or 0.1, 'loop' }
    elseif tweak then
        chain[#chain + 1] = { e[1], 0.12, 'loop' } -- (GrabsTweaks: the tweak comes in over 0.116 s, goes over 0.133 s)
    else
        local into, cyc = variantClips(e, want == 'super')
        chain[#chain + 1] = { into, 0.1 }
        chain[#chain + 1] = { cyc, want == 'super' and 0.2 or 0.1, 'loop' }
    end
    gvar = want
    steps, index = chain, 1
    playStep()
end

-- False while a flip is still turning (landing now means it was under-flipped).
function S3.flipDone()
    if fingering and airGrab(key) and index < #steps then return false end
    if key ~= 'trick' or not flipping then return true end
    local st = prog and prog.stage
    if st == 'dark' then return true end -- (a board caught upside down is judged as that, not as a flip cut short)
    if st and (st:find('^cyc') or st == 'under' or (st == 'in' and prog.t.multi)) then return false end
    return index == #steps and stepT >= stepLen * 0.85
end

-- True while a trick's own clips still need the hands and feet: the takeoff, and the flip itself. An ollie can
-- go straight into a grab (Skate 3's T_Ollie.xml moves to the grabs at any time).
function S3.tricking() return key == 'pop' or (key == 'trick' and flipping) end

-- The grab on the grind, once the hand is on the board: what it adds to the grind's name in the scoring table and
-- what it is called. nil without one.
function S3.grindGrabbed()
    if key ~= 'grind' or not grindGrab or not grindGrab.got then return nil end
    return grindGrab.e[2], grindGrab.e[3]
end

-- True while the rider lies on the board (from the first frame of lying back to the last of sitting up again).
function S3.inCoffin() return key == 'coffin' end

-- Landing. kind: nil (straight) | 'nice' (after a spin) | 'sketchy' (off line) | 'grab'; side = 'fs' | 'bs' | 'dbl'
-- for the last three; hard = a heavy impact.
function S3.land(hard, kind, side)
    if not id then return end
    local name
    if kind == 'grab' then
        name = 'land_grab_' .. (side or 'fs')
    elseif kind == 'nice' then
        name = 'land_nice_' .. (side == 'bs' and 'bs' or 'fs') .. (hard and '_hard' or '')
    elseif kind == 'sketchy' then
        name = 'land_sketchy_' .. (side == 'bs' and 'bs' or 'fs')
    else
        name = (hard and 'land_hard_' or 'land_') .. math.random(1, 3) -- Landing.xml: ChooseRandomLanding numlandings=3
    end
    prog, darkOn, afterPlant = nil, false, false
    run('land', CHAIN[name] or CHAIN.land_1)
end

-- Turn round on the board to ride switch (after rolling fakie). Returns the clip's length; when it has played the
-- caller turns the rider by 180 degrees and calls S3.setMirrored with the other set. Until then the clip holds
-- its last frame.
-- pushing = the rider pushes out of fakie: Skate 3 plays the turn at 1.25 times its speed then (Push.PushFromFakie:
-- "B_SWITCH time=0.15 playBackSpeed=1.25"); the turn on its own is "B_SWITCH time=0.1 playBackSpeed=1.0".
function S3.switchStance(pushing)
    if not id then return 0.0 end
    stopGesture()
    local clip = CHAIN.switch[1][1]
    run('switch', { pushing and { clip, 0.15, nil, 1.25 } or { clip, 0.1 } })
    return stepLen
end

-- What the body should be doing, from the ride state.
local function want(s)
    if s.hippy then
        -- the rider's own jump off the board (which rolls on): the crouch, the jump, and the legs out to land on it
        if s.hippy == 'antic' then return 'hippy_antic' end
        if s.hippy == 'down' then return 'air_extend' end
        return 'hippy_' .. s.hippy
    end
    if s.mode == 'air' then
        -- a flip is played out; an ollie is left at once for a hand on the board or a foot off it
        if key == 'trick' and (flipping or not (s.grab or s.onefoot or s.coffin)) then return key end
        if darkOn then return s.landing and 'dark_extend' or 'dark' end
        -- a moment off the ground is no jump (Skate 3: NaturalAirTime): carry on as before
        if s.natural and key and key ~= 'air' and key ~= 'air_extend' and not ONESHOT[key] then return key end
        -- the coffin starts out of the double grab's own pose (DBLGrab.Into / Cyc -> Coffin) and lasts while asked for
        if s.coffin and (key == 'coffin' or (key == 'grab_dbl' and index == #steps)) then return 'coffin' end
        if s.grab then return 'grab_' .. s.grab end
        if s.onefoot then return 'onefoot_' .. s.onefoot .. (s.landing and '_lo' or '') end
        return s.landing and 'air_extend' or 'air'
    end
    if key == 'pop' then return key end
    if s.mode == 'grind' then return 'grind' end
    if s.skitch then return 'skitch' end
    if key == 'switch' or key == 'revert' then return key end
    if s.coffin and (key == 'coffin' or (key == 'ggrab_dbl' and index == #steps)) then return 'coffin' end
    if s.manual then return 'manual_' .. s.manual end
    if s.antic then return 'antic_' .. s.antic end
    if s.pushing or key == 'push' then return 'push' end
    if key == 'land' then return key end
    if s.ggrab then return 'ggrab_' .. s.ggrab end
    if s.braking then
        if math.abs(s.speed) > 0.15 then return 'brake' end -- Brake.xml: Moving / Stationary split at 0.15 m/s
        return (key == 'brake' or key == 'stand_from_brake') and 'stand_from_brake' or 'stand'
    end
    if key == 'stand_from_brake' and s.idle then return key end
    if s.idle then return 'stand' end -- nothing touched for a while: a foot goes down (Skate 3's NoInputBrake)
    return 'ride'
end

-- balance -1 .. 1 -> the grind clip's l / 0 / r version, with some hysteresis around the current one
local function balanceSide(b, cur)
    local m = S3.mirror and -1.0 or 1.0 -- the mirrored copy of the left-leaning clip leans right
    b = b * m
    local lim = cur == '0' and 0.45 or 0.3
    if b < -lim then return 'l' elseif b > lim then return 'r' end
    return '0'
end

local function isAntic(k) return k ~= nil and k:find('^antic_') ~= nil end
-- 'ggrab_fs' -> 'fs' (the hand on the board on the ground), nil for anything else
local function groundGrab(k) return k ~= nil and k:match('^ggrab_(%a+)$') or nil end

-- Call every frame while riding. s = { mode = 'ground' | 'air' | 'grind', speed, steer (-1 left .. 1 right),
-- antic = 'ollie' | 'shuv' | 'fsshuv' | 'nollie' | 'nshuv' | 'nfsshuv' (crouched for a pop), manual = 'tail' | 'nose',
-- grab = 'fs' | 'bs' | 'dbl' | 'tail' | 'crail' | 'nose' | 'seatbelt' | 'mute' | 'stale', braking, fakie, idle,
-- ggrab = 'fs' | 'bs' | 'dbl' (a hand on the board on the ground), coffin (lie back on it: asked for),
-- onefoot = 'front' | 'back' (that foot off the board in the air), hold / timeToLand / uflip / dcatch (see flipStep),
-- gvar = what the buttons ask for on top of the grab ('tw_up', 'foot_front', 'airwalk', 'nofoot', 'super', 'rocket'),
-- hippy = 'antic' | 'mini' | 'low' | 'high' | 'down' (the hippy jump), hop = how high the rider is above the board in it,
-- pushing (the push button is held), pushKind = 'slow' | 'fast' [.. '_mongo'], x, y, z, heading, pitch,
-- ux, uy, uz = the way up for the rider and the board (the face the board is on, or is turned to in the air: on a bank
--              or the curve of a ramp they stand square to it; heading is then the nose's with that face laid flat),
-- grind = { name, side = 'fs' | 'bs', fakie, balance (-1 .. 1), low (crouched), ledge (false = a round rail),
--           grab = 'fs' | 'bs' | 'dbl' (a hand on the board) },
-- truck = metres from the middle of the deck to each truck,
-- landing = in the air with the ground about to arrive (the legs reach for it),
-- natural = in the air for a moment only, off a kerb (no jump: the pose stays),
-- low = in the air crouched down on the board or lying on it, as the rider left the ground (see the player's Drive) }.
-- Sets S3.lift (how far the feet are tucked above the contact point).
function S3.update(dt, s)
    if not id then return end

    -- finished clips hand over to the next one; a finished one-shot chain frees the state
    if steps and key == 'trick' and prog and prog.stage then
        stepT = stepT + dt
        flipStep(s)
    elseif steps then
        stepT = stepT + dt
        local step = steps[index]
        if not step[3] and stepT >= stepLen then
            if key == 'push' and index == 3 and s.pushing and s.mode == 'ground' then
                -- push still held: straight into the next kick (Push.xml PushCycle -> PushContact)
                local kind = PUSH[s.pushKind] and s.pushKind or 'slow'
                if kind ~= pushKind then
                    pushKind = kind
                    steps = pushChain(kind)
                end
                index = 2
                playStep()
            elseif index < #steps then
                index = index + 1
                playStep()
            elseif ONESHOT[key] and key ~= 'pop' then
                key = nil
            end
        end
    end
    if not id then return end

    local w = want(s)
    local g = s.grind
    if w == 'grind' and g then
        -- which clip set: grind, side, fakie, crouched (stick held down/up to pop out), and the balance
        local low = g.low == true
        local bal = balanceSide(g.balance or 0.0, grindKey and grindKey.bal or '0')
        -- a hand on the board (T_GrindWithGrabs.xml ...): into it (blend 0.3), its cycle, and out again when let go
        if w ~= key or (grindKey and grindKey.name ~= g.name) then grindGrab = nil end
        if grindGrab then
            local gg = grindGrab
            if gg.stage == 'into' and index == #steps then gg.stage, gg.got = 'cyc', true end
            if gg.stage == 'cyc' and g.grab ~= gg.hand then
                gg.stage = 'out'
                steps, index = { { gg.clip .. '_out', 0.1 } }, 1
                playStep()
            elseif gg.stage == 'out' and stepT >= stepLen then
                grindGrab, grindKey = nil, { name = g.name } -- (the grind's own clip again)
            end
        elseif g.grab and w == key and grindKey then
            local clip, e = grindGrabClip(g.name, g.grab, g.side, g.fakie, g.ledge == false)
            if not clip and g.grab == 'dbl' then
                clip, e = grindGrabClip(g.name, 'fs', g.side, g.fakie, g.ledge == false) -- (both hands: the FS one's)
            end
            if clip and hasClip(clipName(clip .. '_into')) then
                grindGrab = { hand = g.grab, e = e, clip = clip, stage = 'into' }
                steps, index = { { clip .. '_into', 0.3 }, { clip .. '_cyc', 0.1, 'loop' } }, 1
                playStep()
            end
        end
        if grindGrab then
            -- (the grab's clips stand for every lean and crouch)
        elseif w ~= key or not grindKey or grindKey.name ~= g.name or grindKey.side ~= g.side or
            grindKey.fakie ~= g.fakie or grindKey.low ~= low or grindKey.bal ~= bal then
            grindKey = { name = g.name, side = g.side, fakie = g.fakie, low = low, bal = bal }
            local clip = grindClip(g.name, g.side, g.fakie, low, bal, g.ledge == false)
            key, steps, index, live, turning, gvar, fingering = 'grind', { { clip, 0.3, 'loop' } }, 1, nil, nil, nil, false
            prog = nil -- (a board caught upside down stays so on the rail: darkOn goes on)
            stepT, stepLen = 0.0, 0.0
            play(steps[1][1], 0.3, true) -- (every grind in the graph: "PLAY B_..._GRIND... time=0.3")
        end
    elseif w == 'skitch' then
        -- holding on to a car: the reach and the pull the first time (both hands), then whatever hold is asked for
        local clip, blend = skitchClip(s.skitch)
        if key ~= w then
            grindKey = nil
            stopGesture()
            local chain = s.skitch.hand and {} or skitchInto(s.skitch.fast, s.skitch.absorb)
            chain[#chain + 1] = { clip, 0.4, 'loop' }
            run(w, chain)
            skitchNow = clip
        elseif index == #steps and clip ~= skitchNow then
            skitchNow = clip
            steps, index = { { clip, blend, 'loop' } }, 1
            playStep()
        end
    elseif w ~= key then
        grindKey = nil
        if w == 'push' then
            pushKind = PUSH[s.pushKind] and s.pushKind or 'slow'
            run('push', pushChain(pushKind))
        elseif isAntic(w) and isAntic(key) then
            -- the stick moved to another crouch (ollie <-> shuvit): straight to that cycle, no second "into"
            run(w, { CHAIN[w][2] })
        elseif key and w:find('^onefoot_') and key:find('^onefoot_') and key:sub(1, 12) == w:sub(1, 12) then
            run(w, { CHAIN[w][2] }) -- the same foot off, legs pulled up <-> reaching for the ground: no second "into"
        elseif afterPlant and airGrab(w) then
            afterPlant = false
            run(w, { CHAIN[w][2] }) -- (PushTrick "LeftGround" goes straight to the grab's cycle)
        elseif airGrab(key) and airGrab(w) then
            local a, b = airGrab(key), airGrab(w)
            local from, to = grabVar(a, gvar), grabVar(b, s.gvar)
            if gvar == 'nofoot' and s.gvar == 'super' and from and to then
                -- both feet off already, and now both hands on: across into the superman (FSGrab DismountTrans.ToSuperman)
                local _, cyc = variantClips(to, true)
                run(w, { { from.toSuper, 0.1, nil, 1.3 }, { cyc, 0.2, 'loop' } })
                gvar = 'super'
            elseif gvar == 'super' and s.gvar == 'nofoot' and from and to then
                local _, cyc = variantClips(to)
                run(w, { { to.fromSuper, 0.3 }, { cyc, 0.1, 'loop' } })
                gvar = 'nofoot'
            elseif GRAB_TR[a .. '2' .. b] and not (from and not gvar:find('^tw_')) then
                run(w, { { GRAB_TR[a .. '2' .. b], 0.1 }, CHAIN[w][2] })
            else
                run(w, CHAIN[w], EXIT[key])
            end
        elseif key == 'coffin' and COFFIN_OUT[w] then
            run(w, { COFFIN_OUT[w], CHAIN[w][2] }) -- sits up into the grab that is still held
        elseif key == 'coffin' and w:find('^grab_') then
            run(w, CHAIN[w], EXIT.coffin)
        elseif groundGrab(key) and groundGrab(w) then
            -- a hand comes off or goes on: the game's own clip from the one grab to the other, then its cycle
            run(w, { GGRAB_TR[groundGrab(key) .. '2' .. groundGrab(w)], CHAIN[w][2] })
        elseif groundGrab(key) and w == 'grab_' .. groundGrab(key) then
            run(w, { CHAIN[w][2] }) -- off the ground with the hand still on the board: on with the air grab's cycle
        elseif key and EXIT[key] and (w == 'ride' or w == 'air' or w == 'stand') then
            run(w, CHAIN[w], EXIT[key])
        else
            run(w, CHAIN[w])
        end
    end
    if not id then return end
    if airGrab(key) and w == key then grabStep(s) end
    if not id then return end

    if gesture and armsBusy(key) then stopGesture() end
    if gesture then
        gesture.t = gesture.t + dt
        if gesture.t >= gesture.len then
            if gesture.step < 3 then gestureStep(gesture.step + 1) else stopGesture() end
        end
    end
    if not id then return end

    -- steer > 0 = turning right. The authored (goofy) lean clips start at the lean to the LEFT; their mirrored
    -- copies start at the lean to the right. Rolling fakie the board turns the other way under the same lean.
    local side = (s.fakie and -1.0 or 1.0) * Config.S3LeanSign * (S3.mirror and -1.0 or 1.0)
    lean = lean + (s.steer * side - lean) * (1.0 - math.exp(-dt * 6.0))
    if live then
        -- step to the static pose nearest the lean, with a little hysteresis so it doesn't flicker
        local wantK = (lean + 1.0) * 0.5 * (LEAN_STEPS - 1)
        if math.abs(wantK - live.k) > 0.65 then
            live.k = leanStep(lean)
            play(live.base .. '_s' .. live.k, 0.25, true)
        end
    elseif turning then
        -- carving: over to the version of the clip for this side
        local side = turnSide(turning.side)
        if side ~= turning.side then
            turning.side = side
            play(turning.set[side], 0.25, true)
        end
    elseif steps and steps[index][3] == 'lean' then
        call('SetPhase', id, 0.5 + 0.5 * lean)
    end

    local contactS, contactH
    if s.mode == 'grind' and g and GRIND[g.name] then
        local d = GRIND[g.name]
        contactS, contactH = d.s, d.h
        if d.truck and s.truck then contactS = d.s < 0 and -s.truck or s.truck end
    end
    S3.lift = call('Drive', id, s.x, s.y, s.z, s.heading, s.pitch, s.mode ~= 'air', contactS or false, contactH or false,
        s.low == true, s.hop or false, false, s.ux, s.uy, s.uz) or 0.0
end
