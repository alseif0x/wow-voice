-- WoWVoz: tells the wow-voz voice control (a Linux program, outside the game)
-- which key does what for this character: the key bound to moving, jumping,
-- autorun, targeting and every action bar button, and the spell, item or macro
-- on each button. wow-voz reads it from this addon's saved data, which the game
-- writes to disk on /reload and on logout.
--
-- It only reads. Nothing here moves the character or casts anything: that is
-- wow-voz pressing the same keys you would.

local ADDON = ...

-- The binding commands wow-voz uses, besides the action bar buttons.
local COMMANDS = {
	"MOVEFORWARD", "MOVEBACKWARD", "TURNLEFT", "TURNRIGHT", "STRAFELEFT", "STRAFERIGHT",
	"JUMP", "TOGGLEAUTORUN", "SITORSTAND", "TARGETNEARESTENEMY", "TARGETNEARESTFRIEND",
	"INTERACTTARGET", "ASSISTTARGET", "FOLLOWTARGET", "TOGGLEWORLDMAP", "TOGGLEBACKPACK",
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

local function Snapshot()
	WoWVozDB = type(WoWVozDB) == "table" and WoWVozDB or {}
	local d = { time = time(), character = (UnitName("player") or "?") .. "-" .. (GetRealmName() or "?"), bindings = {}, buttons = {} }
	for _, c in ipairs(COMMANDS) do
		local keys = Keys(c)
		if #keys > 0 then d.bindings[c] = keys end
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
	WoWVozDB.current = d
	WoWVozDB.characters = WoWVozDB.characters or {}
	WoWVozDB.characters[d.character] = d
end

local pending = false
local function Soon()
	if pending then return end
	pending = true
	C_Timer.After(1, function() pending = false; Snapshot() end)
end

local f = CreateFrame("Frame")
for _, e in ipairs({ "PLAYER_LOGIN", "PLAYER_ENTERING_WORLD", "ACTIONBAR_SLOT_CHANGED", "UPDATE_BINDINGS", "PLAYER_LOGOUT" }) do
	pcall(f.RegisterEvent, f, e)
end
f:SetScript("OnEvent", function(_, event)
	if event == "PLAYER_LOGOUT" then Snapshot() else Soon() end
end)

---------------------------------------------------------------------------
-- On / off: a button, a key binding and /wowvoz. wow-voz can't hear the addon,
-- so the state is shown to it as a tiny square in the top-right corner of the
-- screen (magenta = on, cyan = off; pure colours survive any gamma), which it
-- reads off the game window twice a second.
---------------------------------------------------------------------------

_G.BINDING_HEADER_WOWVOZ = "WoW Voz"
_G.BINDING_NAME_WOWVOZ_TOGGLE = "Voz: activar / desactivar"

local marker, button

local function Enabled()
	return not (WoWVozDB and WoWVozDB.enabled == false)
end

local function Paint()
	local on = Enabled()
	if marker then
		marker.tex:SetColorTexture(on and 1 or 0, on and 0 or 1, 1, 1)
	end
	if button then
		button.text:SetText(on and "Voz: ON" or "Voz: OFF")
		button.text:SetTextColor(on and 0.3 or 0.7, on and 1 or 0.7, on and 0.3 or 0.7)
		button:SetBackdropBorderColor(on and 0.3 or 0.5, on and 0.9 or 0.5, on and 0.3 or 0.5, 1)
	end
end

function WoWVoz_Toggle(state)
	WoWVozDB = type(WoWVozDB) == "table" and WoWVozDB or {}
	if state == nil then state = not Enabled() end
	WoWVozDB.enabled = state and true or false
	Paint()
	print("|cff66ccff[WoW Voz]|r " .. (state and "órdenes de voz ACTIVADAS" or "órdenes de voz DESACTIVADAS"))
end

local function Build()
	-- The marker: 8x8 real pixels (the frame is scaled so one UI unit is one pixel).
	marker = CreateFrame("Frame", "WoWVozMarker", UIParent)
	marker:SetFrameStrata("TOOLTIP")
	local _, h = GetPhysicalScreenSize()
	-- One UI unit = one physical pixel, as WoW AI's strip does (Blizzard's PixelUtil).
	if marker.SetIgnoreParentScale then marker:SetIgnoreParentScale(true) end
	marker:SetScale(768 / (h and h > 0 and h or 1080))
	marker:SetSize(8, 8)
	marker:SetPoint("TOPRIGHT", UIParent, "TOPRIGHT", 0, 0)
	marker.tex = marker:CreateTexture(nil, "OVERLAY")
	marker.tex:SetAllPoints()

	button = CreateFrame("Button", "WoWVozButton", UIParent, "BackdropTemplate")
	button:SetSize(86, 24)
	local s = WoWVozDB and WoWVozDB.button
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
		WoWVozDB.button = { point = point, x = x, y = y }
	end)
	button:SetScript("OnClick", function() WoWVoz_Toggle() end)
	button:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_BOTTOM")
		GameTooltip:SetText("WoW Voz")
		GameTooltip:AddLine("Clic: activar o desactivar las órdenes de voz (wow-voz, fuera del juego, lo ve en menos de un segundo).", 0.8, 0.8, 0.8, true)
		GameTooltip:AddLine("Mayús + arrastrar: mover. También: /wowvoz, o un atajo en Opciones > Atajos > WoW Voz.", 0.6, 0.6, 0.6, true)
		GameTooltip:Show()
	end)
	button:SetScript("OnLeave", function() GameTooltip:Hide() end)
	if WoWVozDB and WoWVozDB.hideButton then button:Hide() end
	Paint()
end

local ui = CreateFrame("Frame")
ui:RegisterEvent("PLAYER_LOGIN")
ui:SetScript("OnEvent", function()
	WoWVozDB = type(WoWVozDB) == "table" and WoWVozDB or {}
	Build()
end)

SLASH_WOWVOZ1 = "/wowvoz"
SlashCmdList["WOWVOZ"] = function(msg)
	msg = (msg or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
	if msg == "on" or msg == "activar" then WoWVoz_Toggle(true)
	elseif msg == "off" or msg == "desactivar" then WoWVoz_Toggle(false)
	elseif msg == "boton" or msg == "botón" then
		WoWVozDB.hideButton = not WoWVozDB.hideButton
		if button then button:SetShown(not WoWVozDB.hideButton) end
	elseif msg == "guardar" or msg == "datos" then
		Snapshot()
		local d = WoWVozDB.current
		local n = 0
		for _, b in ipairs(d.buttons) do if b.name then n = n + 1 end end
		print("|cff66ccff[WoW Voz]|r " .. n .. " botones con algo y " .. #d.buttons .. " teclas anotados. /reload los guarda en disco para wow-voz.")
	else
		WoWVoz_Toggle()
	end
end
