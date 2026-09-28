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

SLASH_WOWVOZ1 = "/wowvoz"
SlashCmdList["WOWVOZ"] = function()
	Snapshot()
	local d = WoWVozDB.current
	local n = 0
	for _, b in ipairs(d.buttons) do if b.name then n = n + 1 end end
	print("|cff66ccff[WoW Voz]|r " .. n .. " botones con algo y " .. #d.buttons .. " teclas anotados. /reload los guarda en disco para wow-voz.")
end
