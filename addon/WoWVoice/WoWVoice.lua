-- WoWVoice: tells the wow-voice voice control (a Linux program, outside the game)
-- which key does what for this character: the key bound to moving, jumping,
-- autorun, targeting and every action bar button, and the spell, item or macro
-- on each button. wow-voice reads it from this addon's saved data, which the game
-- writes to disk on /reload and on logout.
--
-- It only reads. Nothing here moves the character or casts anything: that is
-- wow-voice pressing the same keys you would.

local ADDON = ...

-- What the addon says, in the game's language (Spanish or English).
local T = {
	noTarget = "focus: no target. Select one (Tab or \"next target\") and say \"focus\" again.",
	already = "focus: %s (already)",
	notSet = "focus: the game didn't set the focus.",
	loot = "to loot by voice: auto loot %s, soft interact %s (Options > Controls to change them).",
	bindingToggle = "Voice: on / off",
	on = "Voice: ON", off = "Voice: OFF",
	ordersOn = "voice orders ON", ordersOff = "voice orders OFF",
	focusLabel = "Focus: %s", focusSaid = "focus: %s", noFocus = "no focus",
	tip1 = "Click: turn voice orders on or off (wow-voice, outside the game, sees it within a second).",
	tip2 = "Shift + drag: move. Also: /wowvoice, or a key in Options > Keybindings > WoW Voice.",
	saved = "%d buttons with something on them and %d keys noted. /reload writes them to disk for wow-voice.",
}
if (GetLocale and GetLocale() or ""):match("^es") then
	T = {
		noTarget = "focus: no tienes objetivo. Selecciona uno (Tab o \"siguiente objetivo\") y vuelve a decir \"focus\".",
		already = "foco: %s (ya lo era)",
		notSet = "focus: el juego no ha puesto el foco.",
		loot = "para recoger por voz: despojo automático %s, interacción suave %s (Opciones > Controles para cambiarlo).",
		bindingToggle = "Voz: activar / desactivar",
		on = "Voz: ON", off = "Voz: OFF",
		ordersOn = "órdenes de voz ACTIVADAS", ordersOff = "órdenes de voz DESACTIVADAS",
		focusLabel = "Foco: %s", focusSaid = "foco: %s", noFocus = "sin foco",
		tip1 = "Clic: activar o desactivar las órdenes de voz (wow-voice, fuera del juego, lo ve en menos de un segundo).",
		tip2 = "Mayús + arrastrar: mover. También: /wowvoice, o un atajo en Opciones > Atajos > WoW Voice.",
		saved = "%d botones con algo y %d teclas anotados. /reload los guarda en disco para wow-voice.",
	}
end

-- The binding commands wow-voice uses, besides the action bar buttons.
local COMMANDS = {
	"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT", "STRAFELEFT", "STRAFERIGHT",
	"JUMP", "TOGGLEAUTORUN", "TOGGLERUN", "SITORSTAND", "TARGETNEARESTENEMY", "TARGETNEARESTFRIEND",
	"INTERACTTARGET", "ASSISTTARGET", "FOLLOWTARGET", "TOGGLEWORLDMAP", "TOGGLEBACKPACK", "TOGGLEGAMEMENU",
}

-- Action slot -> the binding command that presses it (the standard bars).
local BARS = {
	{ first = 1, command = "ACTIONBUTTON" },
	{ first = 61, command = "MULTIACTIONBAR1BUTTON" },
	{ first = 49, command = "MULTIACTIONBAR2BUTTON" },
	{ first = 25, command = "MULTIACTIONBAR3BUTTON" },
	{ first = 37, command = "MULTIACTIONBAR4BUTTON" },
}

local function Try(fn, ...)
	if type(fn) ~= "function" then return nil end
	local ok, a, b, c = pcall(fn, ...)
	if ok then return a, b, c end
end

local function Keys(command)
	local k1, k2 = Try(GetBindingKey, command)
	local out = {}
	if k1 then table.insert(out, k1) end
	if k2 then table.insert(out, k2) end
	return out
end

local function ActionName(kind, id)
	if kind == "spell" then return Try(C_Spell and C_Spell.GetSpellName, id) or Try(GetSpellInfo, id) end
	if kind == "item" then return Try(C_Item and C_Item.GetItemNameByID, id) or Try(GetItemInfo, id) end
	if kind == "macro" then return (Try(GetMacroInfo, id)) end
end

---------------------------------------------------------------------------
-- Voice keys: things with no key of their own (focus has none by default, and
-- Forever has no focus frame, but /focus works). Each is a secure macro button
-- clicked through a key nobody uses, bound only for this session as an override
-- (never written into the player's bindings). wow-voice reads which key is which
-- from the snapshot. A real key press runs them, so they work in combat too.
---------------------------------------------------------------------------

-- After "focus": the new focus's name (PLAYER_FOCUS_CHANGED says it), or why
-- there is none. Filled in further down, once the focus display exists.
local focusAnnouncedAt = 0
local function ReportFocus(id)
	local P = "|cff66ccff[WoW Voice]|r "
	if id == "WOWVOICE_FOCUS" and not UnitExists("target") then
		print(P .. T.noTarget)
		return
	end
	local asked = GetTime()
	C_Timer.After(0.4, function()
		if focusAnnouncedAt >= asked then return end -- already said "foco: name"
		if UnitExists("focus") then
			print(P .. T.already:format(UnitName("focus") or "?"))
		else
			print(P .. T.notSet)
		end
	end)
end

local VOICE = {
	{ id = "WOWVOICE_FOCUS", macro = "/focus" },
	{ id = "WOWVOICE_TARGETFOCUS", macro = "/target focus" },
	-- The nearest friendly character as focus, then back to what was targeted.
	{ id = "WOWVOICE_FOCUSFRIEND", macro = "/targetfriend\n/focus\n/targetlasttarget" },
	{ id = "WOWVOICE_CLEARFOCUS", macro = "/clearfocus" },
	{ id = "WOWVOICE_ASSISTFOCUS", macro = "/assist focus" },
}
-- Game actions wow-voice may press that have no keyboard key (unbound, or only on
-- the mouse or the gamepad): they get a free key the same way, as a session
-- override on the action itself. WOWAI_TALK is WoW AI's "Talk" ("oye IA ...").
local NEEDS_KEY = {
	"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT", "STRAFELEFT", "STRAFERIGHT", "JUMP",
	"TOGGLEAUTORUN", "TOGGLERUN", "SITORSTAND", "TARGETNEARESTENEMY", "TARGETNEARESTFRIEND",
	"INTERACTTARGET", "ASSISTTARGET", "FOLLOWTARGET", "TOGGLEWORLDMAP", "TOGGLEBACKPACK", "WOWAI_TALK",
}
local CANDIDATES = {}
for _, mods in ipairs({ "CTRL-SHIFT-", "ALT-SHIFT-", "CTRL-ALT-" }) do
	for n = 9, 12 do table.insert(CANDIDATES, mods .. "F" .. n) end
end
for _, mods in ipairs({ "CTRL-SHIFT-", "ALT-SHIFT-", "CTRL-ALT-" }) do
	for n = 1, 8 do table.insert(CANDIDATES, mods .. "F" .. n) end
end

local function KeyboardKey(k)
	return k and not k:find("BUTTON") and not k:find("^PAD") and not k:find("PAD%d") and not k:find("MOUSEWHEEL")
end
local voiceOwner = CreateFrame("Frame", "WoWVoiceKeys", UIParent)
local voiceKeys = {}

local settingUp = false -- our own overrides fire UPDATE_BINDINGS too; don't answer those

local function SetupVoiceKeys()
	if InCombatLockdown() then return false end
	settingUp = true
	C_Timer.After(1, function() settingUp = false end)
	ClearOverrideBindings(voiceOwner)
	wipe(voiceKeys)
	local taken = {}
	local function FreeKey()
		for _, key in ipairs(CANDIDATES) do
			local action = Try(GetBindingAction, key)
			if not taken[key] and (action == nil or action == "") then
				taken[key] = true
				return key
			end
		end
	end
	for _, cmd in ipairs(NEEDS_KEY) do
		local has = false
		for _, k in ipairs(Keys(cmd)) do if KeyboardKey(k) then has = true end end
		-- WOWAI_TALK only exists when WoW AI is loaded.
		if not has and (cmd ~= "WOWAI_TALK" or (WoWAI and WoWAI.Voice)) then
			local key = FreeKey()
			if key then
				SetOverrideBinding(voiceOwner, true, key, cmd)
				voiceKeys[cmd] = key
			end
		end
	end
	for _, v in ipairs(VOICE) do
		local b = _G[v.id] or CreateFrame("Button", v.id, UIParent, "SecureActionButtonTemplate")
		b:SetAttribute("type", "macro")
		b:SetAttribute("macrotext", v.macro)
		b:RegisterForClicks("AnyDown", "AnyUp")
		if not b.wowvoiceHooked then
			b.wowvoiceHooked = true
			-- Say what the voice order did, once per press.
			b:HookScript("PostClick", function(_, _, down)
				if down == false then return end
				if v.id == "WOWVOICE_FOCUS" or v.id == "WOWVOICE_FOCUSFRIEND" then
					ReportFocus(v.id)
				else
					print("|cff66ccff[WoW Voice]|r " .. v.macro:gsub("\n", " ; "))
				end
			end)
		end
		local key = FreeKey()
		if key then
			SetOverrideBindingClick(voiceOwner, true, key, v.id, "LeftButton")
			voiceKeys[v.id] = key
		end
	end
	return true
end

local function Snapshot()
	WoWVoiceDB = type(WoWVoiceDB) == "table" and WoWVoiceDB or {}
	local d = { time = time(), character = (UnitName("player") or "?") .. "-" .. (GetRealmName() or "?"), locale = Try(GetLocale), bindings = {}, buttons = {} }
	for _, c in ipairs(COMMANDS) do
		local keys = Keys(c)
		if #keys > 0 then d.bindings[c] = keys end
	end
	for id, key in pairs(voiceKeys) do
		d.bindings[id] = d.bindings[id] or {}
		table.insert(d.bindings[id], key)
	end
	for _, bar in ipairs(BARS) do
		for i = 1, 12 do
			local slot = bar.first + i - 1
			local command = bar.command .. i
			local keys = Keys(command)
			local kind, id = Try(GetActionInfo, slot)
			local name = kind and ActionName(kind, id)
			if #keys > 0 or name then
				table.insert(d.buttons, { slot = slot, command = command, keys = keys, kind = kind, id = id, name = name })
			end
		end
	end
	-- The bars can read empty for a moment (loading screens, logging out): keep
	-- the last snapshot that had something on them rather than wiping it.
	local named = 0
	for _, b in ipairs(d.buttons) do if b.name then named = named + 1 end end
	local prev = WoWVoiceDB.characters and WoWVoiceDB.characters[d.character]
	if named == 0 and prev and prev.named and prev.named > 0 then
		d.buttons, named = prev.buttons, prev.named
	end
	d.named = named
	WoWVoiceDB.current = d
	WoWVoiceDB.characters = WoWVoiceDB.characters or {}
	WoWVoiceDB.characters[d.character] = d
end

local pending = false
local function Soon()
	if pending then return end
	pending = true
	C_Timer.After(1, function() pending = false; Snapshot() end)
end

local f = CreateFrame("Frame")
-- Not on PLAYER_LOGOUT: by then the bars read empty. The snapshot taken while
-- playing is what the game writes to disk.
for _, e in ipairs({ "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "ACTIONBAR_SLOT_CHANGED", "UPDATE_BINDINGS", "SPELLS_CHANGED" }) do
	pcall(f.RegisterEvent, f, e)
end
pcall(f.RegisterEvent, f, "PLAYER_REGEN_ENABLED")
-- Looting by voice ("recoger", "despojar"): the interact key works on the corpse
-- in front of you, not only the selected one (soft interact, for keyboard too),
-- and auto loot takes everything, since there's no mouse to pick items with.
-- Once: if you turn them off again, they stay off.
local function SetupLooting()
	WoWVoiceDB = type(WoWVoiceDB) == "table" and WoWVoiceDB or {}
	if WoWVoiceDB.lootSetup or InCombatLockdown() then return end
	if (tonumber(Try(GetCVar, "SoftTargetInteract")) or 3) < 3 then pcall(SetCVar, "SoftTargetInteract", "3") end
	pcall(SetCVar, "autoLootDefault", "1")
	WoWVoiceDB.lootSetup = true
	print("|cff66ccff[WoW Voice]|r " .. T.loot:format(tostring(Try(GetCVar, "autoLootDefault")), tostring(Try(GetCVar, "SoftTargetInteract"))))
end

local keysReady = false
f:SetScript("OnEvent", function(_, event)
	if event == "PLAYER_LOGIN" or event == "PLAYER_REGEN_ENABLED" then SetupLooting() end
	if not keysReady and (event == "PLAYER_LOGIN" or event == "PLAYER_REGEN_ENABLED" or event == "PLAYER_ENTERING_WORLD") then
		keysReady = SetupVoiceKeys()
	elseif event == "UPDATE_BINDINGS" and not InCombatLockdown() and not settingUp then
		SetupVoiceKeys() -- the player changed bindings: pick free keys again
	end
	Soon()
end)

---------------------------------------------------------------------------
-- On / off: a button, a key binding and /wowvoice. wow-voice can't hear the addon,
-- so the state is shown to it as a tiny square in the top-right corner of the
-- screen (magenta = on, cyan = off; pure colours survive any gamma), which it
-- reads off the game window twice a second.
---------------------------------------------------------------------------

_G.BINDING_HEADER_WOWVOICE = "WoW Voice"
_G.BINDING_NAME_WOWVOICE_TOGGLE = T.bindingToggle

local marker, button

local function Enabled()
	return not (WoWVoiceDB and WoWVoiceDB.enabled == false)
end

local function Paint()
	local on = Enabled()
	if marker then
		marker.tex:SetColorTexture(on and 1 or 0, on and 0 or 1, 1, 1)
	end
	if button then
		button.text:SetText(on and T.on or T.off)
		button.text:SetTextColor(on and 0.3 or 0.7, on and 1 or 0.7, on and 0.3 or 0.7)
		button:SetBackdropBorderColor(on and 0.3 or 0.5, on and 0.9 or 0.5, on and 0.3 or 0.5, 1)
	end
end

function WoWVoice_Toggle(state)
	WoWVoiceDB = type(WoWVoiceDB) == "table" and WoWVoiceDB or {}
	if state == nil then state = not Enabled() end
	WoWVoiceDB.enabled = state and true or false
	Paint()
	print("|cff66ccff[WoW Voice]|r " .. (state and T.ordersOn or T.ordersOff))
end

-- Forever has no focus frame: show the focus's name under the button, and say
-- it in the chat when it changes, so "pon el foco" can be seen to work.
local focusText
local function ShowFocus(announce)
	local name = UnitExists and UnitExists("focus") and UnitName("focus") or nil
	if focusText then
		focusText:SetText(name and T.focusLabel:format(name) or "")
	end
	if announce then
		focusAnnouncedAt = GetTime()
		print("|cff66ccff[WoW Voice]|r " .. (name and T.focusSaid:format(name) or T.noFocus))
	end
end

local function Build()
	-- The marker: 8x8 real pixels (the frame is scaled so one UI unit is one pixel).
	marker = CreateFrame("Frame", "WoWVoiceMarker", UIParent)
	marker:SetFrameStrata("TOOLTIP")
	local _, h = GetPhysicalScreenSize()
	-- One UI unit = one physical pixel, as WoW AI's strip does (Blizzard's PixelUtil).
	if marker.SetIgnoreParentScale then marker:SetIgnoreParentScale(true) end
	marker:SetScale(768 / (h and h > 0 and h or 1080))
	marker:SetSize(8, 8)
	marker:SetPoint("TOPRIGHT", UIParent, "TOPRIGHT", 0, 0)
	marker.tex = marker:CreateTexture(nil, "OVERLAY")
	marker.tex:SetAllPoints()

	button = CreateFrame("Button", "WoWVoiceButton", UIParent, "BackdropTemplate")
	button:SetSize(86, 24)
	local s = WoWVoiceDB and WoWVoiceDB.button
	if s and s.point then button:SetPoint(s.point, UIParent, s.point, s.x or 0, s.y or 0)
	else button:SetPoint("TOP", UIParent, "TOP", 180, -8) end
	button:SetBackdrop({
		bgFile = "Interface\\ChatFrame\\ChatFrameBackground",
		edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
		tile = true, tileSize = 16, edgeSize = 12,
		insets = { left = 3, right = 3, top = 3, bottom = 3 },
	})
	button:SetBackdropColor(0.05, 0.05, 0.07, 0.9)
	button.text = button:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	button.text:SetPoint("CENTER")
	button:SetMovable(true)
	button:SetClampedToScreen(true)
	button:RegisterForDrag("LeftButton")
	button:SetScript("OnDragStart", function(self) if IsShiftKeyDown() then self:StartMoving() end end)
	button:SetScript("OnDragStop", function(self)
		self:StopMovingOrSizing()
		local point, _, _, x, y = self:GetPoint()
		WoWVoiceDB.button = { point = point, x = x, y = y }
	end)
	button:SetScript("OnClick", function() WoWVoice_Toggle() end)
	button:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
		GameTooltip:SetText("WoW Voice")
		GameTooltip:AddLine(T.tip1, 0.8, 0.8, 0.8, true)
		GameTooltip:AddLine(T.tip2, 0.6, 0.6, 0.6, true)
		GameTooltip:Show()
	end)
	button:SetScript("OnLeave", function() GameTooltip:Hide() end)
	if WoWVoiceDB and WoWVoiceDB.hideButton then button:Hide() end
	focusText = button:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	focusText:SetPoint("TOP", button, "BOTTOM", 0, -2)
	Paint()
	ShowFocus(false)
end

local ui = CreateFrame("Frame")
ui:RegisterEvent("PLAYER_LOGIN")
pcall(ui.RegisterEvent, ui, "PLAYER_FOCUS_CHANGED")
ui:SetScript("OnEvent", function(_, event)
	if event == "PLAYER_FOCUS_CHANGED" then ShowFocus(true) return end
	WoWVoiceDB = type(WoWVoiceDB) == "table" and WoWVoiceDB or {}
	Build()
end)

SLASH_WOWVOICE1 = "/wowvoice"
SLASH_WOWVOICE2 = "/wowvoz"
SlashCmdList["WOWVOICE"] = function(msg)
	msg = (msg or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
	if msg == "on" or msg == "activar" then WoWVoice_Toggle(true)
	elseif msg == "off" or msg == "desactivar" then WoWVoice_Toggle(false)
	elseif msg == "boton" or msg == "botón" or msg == "button" then
		WoWVoiceDB.hideButton = not WoWVoiceDB.hideButton
		if button then button:SetShown(not WoWVoiceDB.hideButton) end
	elseif msg == "teclas" or msg == "keys" then
		for id, key in pairs(voiceKeys) do
			print("|cff66ccff[WoW Voice]|r " .. key .. " -> " .. id .. "  (" .. tostring(Try(GetBindingAction, key)) .. ")")
		end
	elseif msg == "guardar" or msg == "datos" or msg == "save" then
		Snapshot()
		local d = WoWVoiceDB.current
		local n = 0
		for _, b in ipairs(d.buttons) do if b.name then n = n + 1 end end
		print("|cff66ccff[WoW Voice]|r " .. T.saved:format(n, #d.buttons))
	else
		WoWVoice_Toggle()
	end
end
