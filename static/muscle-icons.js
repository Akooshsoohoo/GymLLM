/* GymLLM muscle icons — one anatomical figure, cropped + highlighted per group.
   Usage:
     <script src="muscle-icons.js"></script>
     <muscle-icon group="chest" size="48"></muscle-icon>           (web component)
     MuscleIcons.svg('legs', {size: 64, variant: 'solo'})          (SVG string, e.g. for server-side templates)
     MuscleIcons.forTags(['chest','shoulders'])  -> 'push'   (one icon for a day; tags or free text)
     MuscleIcons.resolve('pickup basketball')     -> 'basketball'
     MuscleIcons.glyph('swim', {size: 20})        (activity glyph alone, for tiny sizes)
   Colour: highlighted muscles use currentColor. Rest of body uses
     --mi-base (default currentColor) at --mi-base-opacity (default .18).
   Attributes/options: group, size (px, default 48), variant ('map' | 'solo'), crop ('focus' | 'full'). */
(function (root) {
  // Left half of the figure (x < 50); mirrored across x = 50. Center pieces are drawn once.
  var P = {
    head: 'M50 3C56.5 3 60.5 8 60.5 15C60.5 22 56 27 50 27C44 27 39.5 22 39.5 15C39.5 8 43.5 3 50 3Z',
    neck: 'M44.5 26.5C47 28 53 28 55.5 26.5L56.5 33.5C52 35 48 35 43.5 33.5Z',
    trapsF: 'M43 32.5C44 34 46 35 48.5 35.5L48.5 37C42 36.5 36 36.5 31.5 36.5C35 34.5 39 33.5 43 32.5Z',
    delt: 'M30 37.5C23.5 38 20 43 20 50C20 55 21 58.5 22.5 61C25.5 55 29 50 33 46.5C33.5 43 32.5 39.5 30 37.5Z',
    pec: 'M48.8 38.5L48.8 57.5C43 60.5 37 60 33 56.5C32.5 51.5 33 46.5 35 42C39 38.5 44 38 48.8 38.5Z',
    bicep: 'M22.5 64C25.5 58 29 53 33.5 49.5C34.5 57 33.5 66 30.5 75.5C27.5 77.5 24.5 77.5 22 75.5C21 71.5 21.3 67.5 22.5 64Z',
    forearm: 'M22 79C25 80.5 28 80.5 30.5 79C31.5 89 29.8 100 27.8 111L22.3 111C20.3 100 19.5 89 22 79Z',
    hand: 'M22 113.5L28 113.5C29 117 28.5 121.5 25 124C22 121.5 21 117 22 113.5Z',
    abs1: 'M42.3 61.5C44.5 60.8 46.8 60.2 48.8 59.8L48.8 70.5L42 70.5Z',
    abs2: 'M42 72.5L48.8 72.5L48.8 82.5L42 82.5Z',
    abs3: 'M42 84.5L48.8 84.5L48.8 95L42.6 95Z',
    oblique: 'M33.5 59C35.5 61.5 38 62.8 40.3 63L40.3 95C38.5 96 36.8 97.5 35.5 99.5C34.5 88 33.5 74 33.5 59Z',
    lowabs: 'M37 101C39.5 98.5 43 97 48.8 97L48.8 109.5C44 109 39.5 106 37 101Z',
    quad: 'M34.5 104C38 108.5 43 111 48.3 112.5C48.5 126 47.3 141 45 155.5C42 158 38.5 158 36 156C33 141 32.3 122 34.5 104Z',
    shin: 'M36.3 161C39.5 162.5 42.5 162.5 45 161C46 175 45.3 190 43.5 204L38.3 204C36.3 190 35.3 175 36.3 161Z',
    foot: 'M38 206L43.8 206C45.5 207.5 46 210 45.5 212.5L34.5 212.5C34.5 210 36 207.5 38 206Z',
    traps: 'M44 28.5C46 30 48 30.5 48.8 30.5L48.8 62C46.5 56 41.5 47 33.5 38.5C37 36 40.5 33 44 28.5Z',
    rdelt: 'M30 37.5C23.5 38 20 43 20 50C20 55 21 58.5 22.5 61C25.5 55 29 50 32.5 46.5C33 43 32 39.5 30 37.5Z',
    lats: 'M34.3 42C39 47 43.3 54 45.3 61L42.8 80C41.3 86 39.3 90.5 37 94.5C35 80 33.5 60 34.3 42Z',
    erector: 'M47 64.5C47.8 65.5 48.3 66 48.8 66L48.8 99.5L44 99.5C43.5 89 44.5 76 47 64.5Z',
    tricep: 'M22.5 64C25.5 58 29 53 33.5 49.5C34.5 57 33.5 66 30.5 75.5C27.5 77.5 24.5 77.5 22 75.5C21 71.5 21.3 67.5 22.5 64Z',
    glute: 'M35 101.5C38.5 99.5 43.5 100 48.8 101.5L48.8 121.5C44 124.5 38.5 124 34.5 120.5C33 114 33.3 107.5 35 101.5Z',
    ham: 'M34.5 124.5C38.5 127.5 44 127.5 48.3 125.5C48.3 136 47.3 146 45 155.5C42 158 38.5 158 36 156C33.5 145 33.3 134.5 34.5 124.5Z',
    calf: 'M36.3 161C40 161.5 43.5 162.5 45 164C46 173.5 45.3 182 43.3 190C41.3 192.5 38.5 192.5 37 190C35.3 181 35.3 171 36.3 161Z',
    lowshin: 'M38 193.5L43.2 193.5L43.5 204L38.3 204Z',
    heart: 'M58 57C50 51 49 44.5 53 42.3C55.5 41 57.2 42.5 58 44C58.8 42.5 60.5 41 63 42.3C67 44.5 66 51 58 57Z'
  };
  var CENTER = { head: 1, neck: 1, heart: 1 };
  var VIEW = {
    front: ['head', 'neck', 'trapsF', 'delt', 'pec', 'bicep', 'forearm', 'hand', 'abs1', 'abs2', 'abs3', 'oblique', 'lowabs', 'quad', 'shin', 'foot'],
    back: ['head', 'neck', 'traps', 'rdelt', 'lats', 'erector', 'tricep', 'forearm', 'hand', 'glute', 'ham', 'calf', 'lowshin', 'foot']
  };
  var CORE = ['abs1', 'abs2', 'abs3', 'oblique', 'lowabs'];
  var GROUPS = {
    chest:      { label: 'Chest',      view: 'front', crop: [16, 28, 68, 40],  hi: ['pec'] },
    back:       { label: 'Back',       view: 'back',  crop: [14, 24, 72, 80],  hi: ['traps', 'lats', 'erector'] },
    shoulders:  { label: 'Shoulders',  view: 'front', crop: [12, 22, 76, 42],  hi: ['delt', 'trapsF'] },
    arms:       { label: 'Arms',       view: 'front', crop: [12, 34, 76, 92],  hi: ['bicep', 'forearm'] },
    triceps:    { label: 'Triceps',    view: 'back',  crop: [12, 34, 76, 50],  hi: ['tricep'] },
    core:       { label: 'Core',       view: 'front', crop: [26, 54, 48, 58],  hi: CORE },
    legs:       { label: 'Legs',       view: 'front', crop: [24, 98, 52, 118], hi: ['quad', 'shin'], omit: ['hand', 'forearm'] },
    glutes:     { label: 'Glutes',     view: 'back',  crop: [24, 94, 52, 36],  hi: ['glute'], omit: ['hand', 'forearm'] },
    hamstrings: { label: 'Hamstrings', view: 'back',  crop: [24, 98, 52, 98],  hi: ['ham', 'calf'], omit: ['hand', 'forearm'] },
    upper:      { label: 'Upper body', view: 'front', crop: [8, 2, 84, 124],   hi: ['pec', 'delt', 'trapsF', 'bicep', 'forearm'] },
    lower:      { label: 'Lower body', view: 'front', crop: [18, 94, 64, 122], hi: ['quad', 'shin', 'lowabs'], omit: ['hand', 'forearm'] },
    push:       { label: 'Push',       view: 'front', crop: [12, 22, 76, 58],  hi: ['pec', 'delt'] },
    pull:       { label: 'Pull',       view: 'back',  crop: [12, 22, 76, 82],  hi: ['traps', 'lats', 'rdelt', 'forearm'] },
    full:       { label: 'Full body',  view: 'front', crop: [4, 0, 92, 216],   hi: VIEW.front.filter(function (k) { return k !== 'head' && k !== 'neck'; }) },
    cardio:     { label: 'Cardio',     view: 'front', crop: [12, 2, 76, 78],   hi: ['heart'], overlay: ['heart'] }
  };
  // Sports and cardio: full figure with the muscles the activity leans on, plus a badge glyph (24-unit box).
  var F = ' style="fill:var(--mi-badge-ink,#fff);stroke:none"';
  var ACT = {
    run:        { label: 'Run',          view: 'front', hi: ['quad', 'shin', 'heart'], g: '<path d="M3 16h5M2 12h5M4 8h4"/><path d="M10 18c1.5-5 3.5-9 7.5-11 2.2-1 4.5.2 4.5 2.4 0 2.8-3 4-5 6-1.3 1.3-1.5 2.6-3.5 2.6z"/>' },
    walk:       { label: 'Walk',         view: 'front', hi: ['quad', 'shin'], g: '<ellipse cx="8" cy="8.5" rx="3" ry="4.5"' + F + '/><ellipse cx="16" cy="15.5" rx="3" ry="4.5"' + F + '/>' },
    hike:       { label: 'Hike',         view: 'front', hi: ['quad', 'shin', 'lowabs'], g: '<path d="M2 20l7-12 4 6 3-4 6 10z"/>' },
    cycle:      { label: 'Cycle',        view: 'front', hi: ['quad', 'shin'], g: '<circle cx="5.5" cy="16" r="3.8"/><circle cx="18.5" cy="16" r="3.8"/><path d="M5.5 16l4-7h6l3 7M9.5 9l3 7h-7M13.5 6h3"/>' },
    swim:       { label: 'Swim',         view: 'back',  hi: ['traps', 'lats', 'rdelt', 'tricep'], g: '<path d="M2 14c2-2 3.5-2 5 0s3 2 5 0 3.5-2 5 0 3 2 5 0M2 19.5c2-2 3.5-2 5 0s3 2 5 0 3.5-2 5 0 3 2 5 0"/><circle cx="16" cy="6.5" r="2.4"' + F + '/>' },
    row:        { label: 'Row',          view: 'back',  hi: ['lats', 'traps', 'rdelt', 'forearm', 'glute', 'ham'], g: '<path d="M3 20L17 6"/><path d="M15.5 3.5l5 5-3 3-5-5z"' + F + '/><path d="M2 15c2-1.5 3.5-1.5 5 0s3 1.5 5 0"/>' },
    climb:      { label: 'Climb',        view: 'back',  hi: ['lats', 'traps', 'rdelt', 'forearm'], g: '<circle cx="7" cy="6" r="2.4"' + F + '/><circle cx="14" cy="11" r="2.4"' + F + '/><circle cx="8" cy="17.5" r="2.4"' + F + '/><path d="M19 2v20"/>' },
    yoga:       { label: 'Yoga',         view: 'front', hi: CORE.concat(['quad']), g: '<path d="M12 4.5c3 3 3 8 0 12-3-4-3-9 0-12zM2.5 10.5c4 0 7.5 2 9.5 6.5-4.5 1-8.5-1.5-9.5-6.5zM21.5 10.5c-4 0-7.5 2-9.5 6.5 4.5 1 8.5-1.5 9.5-6.5z"/><path d="M4 20.5h16"/>' },
    pilates:    { label: 'Pilates',      view: 'front', hi: CORE, g: '<circle cx="12" cy="12" r="7.5"/><path d="M3 9.5v5M21 9.5v5"/>' },
    hiit:       { label: 'HIIT',         view: 'front', hi: ['quad', 'shin', 'delt', 'pec', 'heart'].concat(CORE), g: '<path d="M13.5 2L5 13.5h6L10 22l8.5-12h-6z"' + F + '/>' },
    jumprope:   { label: 'Jump rope',    view: 'front', hi: ['shin', 'delt', 'forearm', 'heart'], g: '<path d="M6 3v6M18 3v6M6 9c0 13 12 13 12 0"/>' },
    stairs:     { label: 'Stairs',       view: 'back',  hi: ['glute', 'ham', 'calf'], g: '<path d="M2.5 20.5h5v-5h5v-5h5v-5h4"/>' },
    boxing:     { label: 'Boxing',       view: 'front', hi: ['delt', 'pec', 'forearm', 'oblique'], g: '<path d="M7.5 20.5v-3.5C5 16 4 13.5 4 11V8c0-3 2-5 5-5h4.5c3 0 5 2 5 5v4.5c0 2-1 3.8-3 4.8v3.2z"/><path d="M4 11h4.5c1.2 0 2 .8 2 2M7.5 17h8"/>' },
    martial:    { label: 'Martial arts', view: 'front', hi: ['delt', 'oblique', 'quad', 'forearm'], g: '<path d="M2 10h20M2 14h20M10.5 14l-3 7.5M13.5 14l3 7.5"/><rect x="9.5" y="8.5" width="5" height="7" rx="1.2"' + F + '/>' },
    basketball: { label: 'Basketball',   view: 'front', hi: ['quad', 'shin', 'delt', 'forearm'], g: '<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19M12 2.5v19M5.3 5.3c3.4 3.4 3.4 10 0 13.4M18.7 5.3c-3.4 3.4-3.4 10 0 13.4"/>' },
    soccer:     { label: 'Soccer',       view: 'front', hi: ['quad', 'shin', 'lowabs'], g: '<circle cx="12" cy="12" r="9.5"/><path d="M12 7.8l3.6 2.6-1.4 4.2H9.8l-1.4-4.2z"' + F + '/><path d="M12 7.8V2.5M15.6 10.4l5-1.6M14.2 14.6l3 4.3M9.8 14.6l-3 4.3M8.4 10.4l-5-1.6"/>' },
    tennis:     { label: 'Tennis',       view: 'front', hi: ['delt', 'forearm', 'oblique', 'quad'], g: '<ellipse cx="9.5" cy="9.5" rx="6.5" ry="7" transform="rotate(-45 9.5 9.5)"/><path d="M14.3 14.3L21 21M6 9l4.5 4.5M9 6l4.5 4.5"/>' },
    paddle:     { label: 'Pickleball',   view: 'front', hi: ['delt', 'forearm', 'oblique', 'quad'], g: '<circle cx="9.5" cy="9.5" r="7"/><path d="M14.5 14.5L20.5 20.5"/><circle cx="19.5" cy="5" r="2.2"' + F + '/>' },
    golf:       { label: 'Golf',         view: 'front', hi: ['oblique', 'forearm', 'abs2', 'abs3'], g: '<path d="M8 21V3l10 4.2L8 11.4"/><path d="M4 21h9"/>' },
    baseball:   { label: 'Baseball',     view: 'front', hi: ['delt', 'oblique', 'forearm'], g: '<circle cx="12" cy="12" r="9.5"/><path d="M6.5 4c2.8 4.3 2.8 11.7 0 16M17.5 4c-2.8 4.3-2.8 11.7 0 16"/>' },
    volleyball: { label: 'Volleyball',   view: 'front', hi: ['delt', 'quad', 'shin'], g: '<circle cx="12" cy="12" r="9.5"/><path d="M12 2.5c-1.2 5 .8 8 4.5 9.5M12 12c-4 2.2-7.2 1.6-9-1.2M12 12c1 3.4 4.2 6.2 8 5.6"/>' },
    football:   { label: 'Football',     view: 'front', hi: ['quad', 'delt', 'pec'], g: '<ellipse cx="12" cy="12" rx="10.5" ry="6.2" transform="rotate(-45 12 12)"/><path d="M9 15l6-6M10.3 12.3l1.4 1.4M11.3 11.3l1.4 1.4M12.3 10.3l1.4 1.4"/>' },
    hockey:     { label: 'Hockey',       view: 'front', hi: ['quad', 'oblique', 'forearm'], g: '<path d="M16 2.5l-6.2 15.2c-.6 1.6-1.6 2.3-3.2 2.3H2.5"/><ellipse cx="18" cy="19.5" rx="3.5" ry="1.8"' + F + '/>' },
    ski:        { label: 'Ski & snow',   view: 'front', hi: ['quad', 'shin', 'abs1', 'abs2', 'abs3'], g: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17L20.7 7M9 3.8l3 2.2 3-2.2M9 20.2l3-2.2 3 2.2"/>' },
    dance:      { label: 'Dance',        view: 'front', hi: ['quad', 'shin', 'lowabs', 'oblique'], g: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.8"' + F + '/><circle cx="17.5" cy="16" r="2.8"' + F + '/>' },
    sport:      { label: 'Sport',        view: 'front', hi: VIEW.front.filter(function (k) { return k !== 'head' && k !== 'neck'; }), g: '<circle cx="12" cy="13.5" r="8"/><path d="M12 13.5V9.5M9.5 2.5h5M12 2.5v3M18.5 6l1.5-1.5"/>' }
  };
  var ALIAS = { pecs: 'chest', lats: 'back', delts: 'shoulders', biceps: 'arms', abs: 'core', quads: 'legs', glute: 'glutes', hams: 'hamstrings', 'upper body': 'upper', 'lower body': 'lower', 'full body': 'full', bike: 'cycle', cycling: 'cycle', pickleball: 'paddle', padel: 'paddle' };
  // Free text -> id. First match wins, so specific phrases sit above broad ones.
  var WORDS = [
    [/pickle|padel|paddle ?ball/, 'paddle'], [/tennis|squash|racquet|badminton/, 'tennis'],
    [/basketball|hoops|shoot ?around/, 'basketball'], [/soccer|futsal|footy/, 'soccer'], [/american football|flag football|\bfootball\b/, 'football'],
    [/volleyball/, 'volleyball'], [/baseball|softball|batting cage/, 'baseball'], [/golf|driving range/, 'golf'], [/hockey|lacrosse/, 'hockey'],
    [/\bski(ing|s)?\b|snowboard|\bsnow/, 'ski'], [/boxing|kickbox|sparring|heavy bag|\bbox\b(?! ?jump)/, 'boxing'], [/jiu|bjj|judo|karate|muay|mma|taekwondo|wrestl|martial/, 'martial'],
    [/dance|zumba|barre/, 'dance'], [/pilates|reformer/, 'pilates'], [/yoga|stretch|mobility|flexib/, 'yoga'],
    [/climb|boulder/, 'climb'], [/hike|hiking|trail|ruck/, 'hike'], [/swim|laps? in the pool|pool/, 'swim'], [/rowing|\berg\b|rower|kayak|canoe|paddle ?board/, 'row'],
    [/bike|cycl|spin|peloton/, 'cycle'], [/jump ?rope|skipping/, 'jumprope'], [/stair|stepmill|step ?machine|elliptical/, 'stairs'],
    [/hiit|box jump|plyo|circuit|crossfit|bootcamp|tabata|burpee|emom|amrap|wod/, 'hiit'],
    [/\bran\b|\brun|jog|sprint|treadmill|marathon|\d+ ?k\b/, 'run'], [/walk|steps|stroll/, 'walk'],
    [/hip thrust|glute bridge|kickback|glute/, 'glutes'], [/rdl|romanian|leg curl|hamstring|good morning/, 'hamstrings'],
    [/squat|lunge|leg press|leg extension|calf|split squat|step ?up|quad|\blegs?\b/, 'legs'],
    [/bench|chest|fly|flye|push ?-?up|dip|pec/, 'chest'], [/deadlift|pull ?-?up|chin ?-?up|lat |pulldown|\brows?\b|back/, 'back'],
    [/overhead|ohp|shoulder|lateral raise|military|arnold|delt/, 'shoulders'], [/tricep|skull ?crusher|pushdown/, 'triceps'],
    [/curl|bicep|forearm|arm/, 'arms'], [/plank|crunch|sit ?-?up|ab |abs|core|hollow|russian twist|leg raise/, 'core'],
    [/push day/, 'push'], [/pull day/, 'pull'], [/upper/, 'upper'], [/lower/, 'lower'], [/full body|total body/, 'full'], [/cardio|conditioning/, 'cardio'],
    [/sport|game|match|practice|league/, 'sport']
  ];
  var uid = 0;
  var MIRROR = ' transform="matrix(-1 0 0 1 100 0)"';

  function resolve(text) {
    var t = ' ' + String(text || '').toLowerCase() + ' ';
    for (var i = 0; i < WORDS.length; i++) if (WORDS[i][0].test(t)) return WORDS[i][1];
    return null;
  }
  function norm(g) {
    var k = String(g || '').toLowerCase().trim();
    if (GROUPS[k] || ACT[k]) return k;
    if (ALIAS[k]) return ALIAS[k];
    return resolve(k) || 'full';
  }
  function def(key) { return GROUPS[key] || ACT[key]; }

  function glyph(activity, o) {
    o = o || {};
    var A = ACT[norm(activity)] || ACT.sport, size = o.size || 24;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="' + size + '" height="' + size + '" role="img" style="--mi-badge-ink:currentColor"><title>' + A.label + '</title><g fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">' + A.g + '</g></svg>';
  }

  function svg(group, o) {
    o = o || {};
    var key = norm(group), G = def(key), A = ACT[key], size = o.size || 48, solo = o.variant === 'solo';
    if (A && o.variant === 'glyph') return glyph(key, o);
    var box = (o.crop === 'full' || A) ? [4, 0, 92, 216] : G.crop;
    var side = Math.max(box[2], box[3]) * 1.08, cx = box[0] + box[2] / 2, cy = box[1] + box[3] / 2;
    var x0 = cx - side / 2, y0 = cy - side / 2;
    var vb = [x0, y0, side, side].map(function (n) { return +n.toFixed(2); }).join(' ');
    var cid = 'mi' + (++uid);
    var hi = {}; G.hi.forEach(function (k) { hi[k] = 1; });
    var omit = {}; (o.crop === 'full' ? [] : G.omit || []).forEach(function (k) { omit[k] = 1; });
    var base = 'fill:var(--mi-base,currentColor);fill-opacity:var(--mi-base-opacity,.18)';
    var out = [], top = [];
    VIEW[G.view].concat(hi.heart ? ['heart'] : []).forEach(function (k) {
      var on = !!hi[k];
      if ((solo && !on) || omit[k]) return;
      var attr = on ? 'fill="currentColor"' : 'style="' + base + '"';
      var s = '<path d="' + P[k] + '" ' + attr + '/>';
      if (!CENTER[k]) s += '<path d="' + P[k] + '" ' + attr + MIRROR + '/>';
      (on ? top : out).push(s);
    });
    var badge = '';
    if (A) {
      var r = side * 0.2, bx = cx + side * 0.27, by = cy + side * 0.28, sc = (r * 1.25) / 24;
      badge = '<circle cx="' + bx.toFixed(2) + '" cy="' + by.toFixed(2) + '" r="' + r.toFixed(2) + '" fill="currentColor"/>' +
        '<g transform="translate(' + (bx - 12 * sc).toFixed(2) + ' ' + (by - 12 * sc).toFixed(2) + ') scale(' + sc.toFixed(3) + ')" fill="none" stroke="var(--mi-badge-ink,#fff)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' + A.g + '</g>';
    }
    var title = o.title === false ? '' : '<title>' + (o.title || G.label) + '</title>';
    var clip = '<defs><clipPath id="' + cid + '"><rect x="' + box[0] + '" y="' + box[1] + '" width="' + box[2] + '" height="' + box[3] + '"/></clipPath></defs>';
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + vb + '" width="' + size + '" height="' + size + '" role="img" data-muscle="' + key + '">' + title + clip + '<g clip-path="url(#' + cid + ')">' + out.join('') + top.join('') + '</g>' + badge + '</svg>';
  }

  var UPPER = ['chest', 'back', 'shoulders', 'arms', 'triceps'], LOWER = ['legs', 'glutes', 'hamstrings'];
  // Accepts tags or free text ("ran 5k", "pickup basketball", "bench 185") and returns one id for the day.
  function forTags(tags) {
    var t = {}, acts = [];
    (typeof tags === 'string' ? tags.split(/[,;\n]| and | then /) : tags || []).forEach(function (x) {
      var k = norm(x); if (!String(x).trim()) return;
      t[k] = 1; if (ACT[k] && acts.indexOf(k) < 0) acts.push(k);
    });
    var up = UPPER.filter(function (g) { return t[g]; }), lo = LOWER.filter(function (g) { return t[g]; });
    if (up.length && lo.length) return 'full';
    if (up.length === 1 && !lo.length) return up[0];
    if (lo.length === 1 && !up.length) return lo[0];
    if (lo.length) return 'lower';
    if (up.length) {
      var push = up.every(function (g) { return g === 'chest' || g === 'shoulders' || g === 'triceps'; });
      var pull = up.every(function (g) { return g === 'back' || g === 'arms'; });
      return push ? 'push' : pull ? 'pull' : 'upper';
    }
    if (acts.length === 1) return acts[0];
    if (acts.length > 1) return 'cardio';
    if (t.core) return 'core';
    if (t.cardio) return 'cardio';
    return 'full';
  }

  function list(obj) { return Object.keys(obj).map(function (k) { return { id: k, label: obj[k].label }; }); }
  var api = { svg: svg, glyph: glyph, resolve: resolve, forTags: forTags, groups: list(GROUPS), activities: list(ACT), label: function (g) { return def(norm(g)).label; } };
  root.MuscleIcons = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  if (root.customElements && !root.customElements.get('muscle-icon')) {
    root.customElements.define('muscle-icon', class extends HTMLElement {
      static get observedAttributes() { return ['group', 'size', 'variant', 'crop', 'label']; }
      connectedCallback() { this.style.display = this.style.display || 'inline-flex'; this.render(); }
      attributeChangedCallback() { if (this.isConnected) this.render(); }
      render() {
        this.innerHTML = svg(this.getAttribute('group'), {
          size: +this.getAttribute('size') || 48, variant: this.getAttribute('variant') || 'map',
          crop: this.getAttribute('crop') || 'focus', title: this.getAttribute('label') || undefined
        });
      }
    });
  }
})(typeof window !== 'undefined' ? window : globalThis);
