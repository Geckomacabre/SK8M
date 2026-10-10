fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name 'skateboard'
description 'Rideable skateboard: push, carve, ollie, flips, spins and bails. Skate 3 flavoured.'
version '0.4.0'

shared_script 'config.lua'
client_scripts { 'flick.lua', 'tuning.lua', 'surface.lua', 's3.lua', 'dev.lua', 'deck.lua', 'client.lua', 'selftest.lua', 'shop.lua', 'engine.lua' }
server_scripts { 'server.lua', 'deck_server.lua' }

-- the sounds (built in the browser, see html/sound.js)
ui_page 'html/sound.html'
files { 'html/sound.html', 'html/sound.js', 'html/designer.html', 'html/designer.js', 'html/designer.css',
        -- Skate 3's engine, hosted in the page (engine.lua; the engine itself and its data are in skate3_assets)
        'html/engine/host.js', 'html/engine/worker.js', 'html/engine/engine.js', 'html/engine/wasi_mem.js',
        'html/engine/ground.js' }
