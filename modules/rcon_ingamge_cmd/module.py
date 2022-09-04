
# Works with Python 3.6
# Discord 1.2.2
import asyncio
from collections import Counter
from collections import deque
import concurrent.futures
import json
import os
import sys
import traceback
import discord
from discord.ext import commands
from discord.ext.commands import has_permissions, CheckFailure
import prettytable
import geoip2.database
import datetime
import shlex, subprocess
import psutil
import inspect
import time
from random import randint
import glob

from modules.core.utils import CommandChecker, sendLong, CoreConfig, Tools
from modules.core.Log import log
from modules.core.config import Config
from .cmdengine import RconCommandEngine

class AccountVerificationCode():
    def __init__(self, authorID, timelimit = 60):
        self.authorID = authorID
        self.code = randint(1000, 9999)
        self.timelimit = timelimit
    
    def __str__(self):
        return str(self.code)
    
    def __lt__(self, other):
        return self.code < other
    def __le__(self, other):
        return self.code <= other
    def __eq__(self, other):
        return self.code == other
    def __ne__(self, other):
        return self.code != other
    def __gt__(self, other):
        return self.code > other
    def __ge__(self, other):
        return self.code >= other
        
    async def destruct(self, obj):
        await asyncio.sleep(self.timelimit)
        del obj

class PermissionConfig(CoreConfig):
    path = os.path.dirname(os.path.realpath(__file__))
    
    def __init__(self, bot):
        CoreConfig.bot = bot
        self.cfgPermissions_Roles = {}
        
        files = glob.glob(type(self).path+"/permissions_*.json")
        if(len(files)==0):
            self.generate_default_settings()
        else:
            self.load_role_permissions()
    
    def load_role_permissions(self):
        files = glob.glob(type(self).path+"/permissions_*.json")
        if(len(files)==0):
            self.generate_default_settings()
        for file in files:
            role = os.path.basename(file).replace("permissions_", "").replace(".json", "")
            self.cfgPermissions_Roles[role] = Config(type(self).path+"/permissions_{}.json".format(role))
        
        #add new commands (for new modules)
        for role, data in self.cfgPermissions_Roles.items():
            for Command in RconCommandEngine.commands:
                cmd = "command_"+str(Command["cmd"])
                if(cmd not in self.cfgPermissions_Roles[role]):
                    self.cfgPermissions_Roles[role][cmd] = False
                    
    def generate_default_settings(self):
        for role in ["@everyone", "Admin"]:
            self.cfgPermissions_Roles[role] = type(self).cfg.new(type(self).path+"/permissions_{}.json".format(role))
            
            if(role in ["@everyone"]):
                val = False
            else:
                val = True
                
            for Command in RconCommandEngine.commands:
                self.cfgPermissions_Roles[role]["command_"+str(Command["cmd"])] = val
                
    def deall_role(self, data):
        role = data["role"][0]
        for Command in RconCommandEngine.commands:
            self.cfgPermissions_Roles[role]["command_"+str(Command["cmd"])] = False    
    
    def all_role(self, data):
        role = data["role"][0]
        for Command in RconCommandEngine.commands:
            self.cfgPermissions_Roles[role]["command_"+str(Command["cmd"])] = True
        
    def add_role(self, data):
        role = data["add_role"][0]
        log.info("Created new role: '{}'".format(role))
        self.cfgPermissions_Roles[role] = type(self).cfg.new(type(self).path+"/permissions_{}.json".format(role))

        for Command in RconCommandEngine.commands:
            self.cfgPermissions_Roles[role]["command_"+str(Command["cmd"])] = False

# Registering functions, and interacting with the discord bot.
class CommandRconIngameComs(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.path = os.path.dirname(os.path.realpath(__file__))
        
        self.cfg = CoreConfig.modules["modules/rcon_ingamge_cmd"]["general"]
        
        self.PermissionConfig = PermissionConfig(self.bot)
        
        self.afkLock = False
        self.afkTime = -1
        self.account_verify_codes = []
        
        
        
        self.user_data = {}
        if(os.path.isfile(self.path+"/userdata.json")):
            self.user_data = json.load(open(self.path+"/userdata.json","r"))
        
        self.RconCommandEngine = RconCommandEngine
        RconCommandEngine.cogs = self.bot.cogs
        RconCommandEngine.command_prefix = self.cfg["command_prefix"]
        
        #God please have mercy on me for doing this:
        #RconCommandEngine.checkPermission = self.checkPermission #MonkeyPatching
        #RconCommandEngine.rate_limit_commands.append("afk")
        #RconCommandEngine.admins.append("Yoshi_E") this simply bypasses cooldowns for cmds
        #RconCommandEngine.admins.append("[H] Tom")
        #RconCommandEngine.admins.append("zerty")
        
        asyncio.ensure_future(self.on_ready())
        
    async def on_ready(self):
        try:
            await self.bot.wait_until_ready()
            self.CommandRcon = self.bot.cogs["CommandRcon"]
            
           # self.bot.cogs["CommandRcon"].arma_rcon = self.CommandRcon.arma_rcon
        except Exception as e:
            log.error(e)

        
    def set_user_data(self, user_id=0, field="", data=[]):
        if(user_id != 0):
            self.user_data[user_id] = {field: data}
        #save data
        with open(self.path+"/userdata.json", 'w') as outfile:
            json.dump(self.user_data, outfile, sort_keys=True, indent=4, separators=(',', ': '))
  
    async def checkPermission(self, rctx, cmd):
        try:
            cmd = "command_{}".format(cmd)
            pr = self.PermissionConfig.cfgPermissions_Roles
            role = "@everyone"
            #check if everybody can use it
            if(cmd in pr[role] and pr[role][cmd]):
                #anyone can use the cmd
                return True
            #check if user can use it
            #Lookup user in linked accounts:
            for user_id,data in self.user_data.items():
                log.info("{} {}".format(data["account_arma3"], rctx.user_guid))
                if("account_arma3" in data and data["account_arma3"][0] == rctx.user_guid):
                    #check if user has permission:
                    server = self.bot.guilds[0]
                    user = discord.utils.get(server.members, id=int(user_id))
                    if(user):
                        #get user roles, and check if role has permission
                        for role in user.roles:
                            if str(role) in pr.keys():
                                if(cmd in pr[str(role)] and pr[str(role)][cmd]):
                                    return True
            return False       
        except Exception as e:
            log.print_exc()
            log.error(e)
            return False
            
    @CommandChecker.command(name='linkAccount',
        brief="Link you discord account with your arma 3 ingame account.",
        aliases=['linkaccount'],
        pass_context=True)
    async def linkAccount(self, ctx): 
        code = AccountVerificationCode(ctx.author.id, timelimit = 60*5)
        asyncio.ensure_future(code.destruct(code))
        self.account_verify_codes.append(code)
        
        log.info("[ingcmd] Generated code '{}' for user {} [{}]".format(code, ctx.author.name, ctx.author.id))
        msg = "To verify your account, use the in game command '{}link {}'\nThe code is valid for 5min.".format(RconCommandEngine.command_prefix, code)
        
        if(str(ctx.author.id) in self.user_data and "account_arma3" in self.user_data[str(ctx.author.id)]):
            msg = "You account is already linked.\n"+msg
        await ctx.author.send(msg)  #handle the case that the user blocked the bot / does not have DM enabled

        await asyncio.sleep(60*5)
        if(not (str(ctx.author.id) in self.user_data and "account_arma3" in self.user_data[str(ctx.author.id)])):
            await ctx.author.send("Code expired")  
        
    def verifyAccount(self, verifyCode, link_id):
        try:
            verifyCode = self.account_verify_codes.index(verifyCode)
        except ValueError:
            log.info("Account not found ({}, {})".format(verifyCode, link_id))
            verifyCode = None
        else: 
            verifyCode = self.account_verify_codes[verifyCode]
        if(verifyCode):
            log.info("[ingcmd] Linked account '{}' with arma 3 '{}'".format(verifyCode.authorID, link_id))
            self.set_user_data(str(verifyCode.authorID), "account_arma3", link_id)
            return True
        return False
       
###################################################################################################
#####                                    In game commands                                      ####
################################################################################################### 

    @RconCommandEngine.command(name="ping")  
    async def ping(self, rctx):
        await rctx.say("Pong!")    

    @RconCommandEngine.command(name="help")  
    async def help(self, rctx):
        for Command in RconCommandEngine.commands:
            if(len(Command["kwargs"]) > 2):
                await rctx.say("{} {}".format(Command["cmd"], Command["kwargs"][2:]))   
            else:
                await rctx.say("{}".format(Command["cmd"]))    
        
    @RconCommandEngine.command(name="players")  
    async def players(self, rctx):
        playerList = await self.bot.cogs["CommandRcon"].arma_rcon.getPlayersArray()
        msg = ""
        for id, ip, ping, guid, name in playerList:
            msg += "\n{} | {}".format(id, name[:22]) #.ljust(20, " ") #.rjust(3, " ")
            if(len(msg)>200):
                await rctx.say(msg)
                msg = "\n"
        if(msg != ""):
            await rctx.say(msg)    
            
    @RconCommandEngine.command(name="afk")  
    async def check_afk(self, rctx, beid):
        time_to_respond = 300 #checks for 5min (10*30s), gives a warning every 30s
        channel = rctx.channel
        user = rctx.user
        ctx_beid = rctx.user_beid
        
        
        if(self.afkLock == True):
            await rctx.say("An AFK check is already in progess, please wait {}s.".format(self.afkTime))
            return False
        self.afkLock = True
        
        players = await self.bot.cogs["CommandRcon"].arma_rcon.getPlayersArray()
        player_name = None
        for player in players:
            if(int(player[0]) == int(beid)):
                player_name = player[4]
        if(player_name!=None and player_name.endswith(" (Lobby)")): #Strip lobby from name
            player_name = player_name[:-8]
        
        if(player_name==None):
            await rctx.say("Failed to find player with that ID")
            self.afkLock = False
            return False
        msg= "Starting AFK check for: {} - {}. He has {} seconds to respond".format(player_name, beid, time_to_respond)
        await rctx.say(msg)
        
        already_active = False
        for i in range(0, time_to_respond): 
            self.afkTime = time_to_respond-i
            if(self.CommandRcon.playerTypesMessage(player_name)):
                if(i==0):
                    already_active = True
                    await rctx.say("Player was recently active. Canceling AFK check.")  
                else:
                    await rctx.say("Player responded in chat. Canceling AFK check.")  
                if(already_active == False):
                    await self.bot.cogs["CommandRcon"].arma_rcon.sayPlayer(beid,  "Thank you for responding in chat.")
                self.afkLock = False
                return True
            if((i % 30) == 0):
                try:
                    for k in range(0, 3):
                        await self.bot.cogs["CommandRcon"].arma_rcon.sayPlayer(beid, "Type something in chat or you will be kicked for being AFK. ("+str(round(i/30)+1)+"/10)")
                except: 
                    log.error("Failed to send command sayPlayer (checkAFK)")
            await asyncio.sleep(1)
        if(self.CommandRcon.playerTypesMessage(player_name)):
            if(i==0):
                already_active = True
            await rctx.say("Player responded in chat. Canceling AFK check.")  
            if(already_active == False):
                try:
                    await self.bot.cogs["CommandRcon"].arma_rcon.sayPlayer(beid, "Thank you for responding in chat.")
                except:
                    log.error("Failed to send command sayPlayer")
            self.afkLock = False        
            return False
        else:
            await self.bot.cogs["CommandRcon"].arma_rcon.kickPlayer(beid, "AFK too long (user_check by {})".format(user))
            await rctx.say("``{}`` did not respond and was kicked for being AFK".format(player_name))
        self.afkLock = False

    @RconCommandEngine.command(name="link")  
    async def linkAcc(self, rctx, verifyCode):
        try:
            playerBEID, playerGUID = await RconCommandEngine.getPlayerBEID(rctx.user)
            if(self.verifyAccount(int(verifyCode), playerGUID)):
                await rctx.say("Account successfully linked!")
            else:
                await rctx.say("Invalid code")
        except ValueError as e:
            pass


###################################################################################################
#####                                In game commands  (BEC)                                   ####
###################################################################################################      
    @RconCommandEngine.command(name="kpl")  
    async def kpl(self, rctx, beid):
        await self.bot.cogs["CommandRcon"].arma_rcon.kickPlayer(beid, "Kicked by '{}'".format(rctx.user))     
    
    @RconCommandEngine.command(name="bpl")  
    async def bpl(self, rctx, beid, time):
        await self.bot.cogs["CommandRcon"].arma_rcon.banPlayer(player_id=beid, reason="Banned for {}min ({})' ".format(time, rctx.user), time=time) 
    
    @RconCommandEngine.command(name="bpl60")  
    async def bpl60(self, rctx, beid):
        await self.bot.cogs["CommandRcon"].arma_rcon.banPlayer(player_id=beid, reason="Banned by '{}' for 60min".format(rctx.user), time = 60)     
        
    @RconCommandEngine.command(name="say")  
    async def say(self, rctx, message):
        await self.bot.cogs["CommandRcon"].arma_rcon.sayGlobal(message)    
    
    @RconCommandEngine.command(name="reassign")  
    async def reassign(self, rctx, message):
        await self.bot.cogs["CommandRcon"].arma_rcon.reassign()    
        
    #@RconCommandEngine.command(name="score", cogs=["CommandJMW"])  
    async def score(self, rctx):
        log.info("##{} {}".format(self, rctx))
        pass#await self.bot.cogs["CommandRcon"].arma_rcon.reassign()
            
        
class CommandRconTaskScheduler(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.path = os.path.dirname(os.path.realpath(__file__))
        
        #self.bot.cogs["CommandRcon"].arma_rcon_adminNotification = CoreConfig.cfg.new(self.path+"/rcon_scheduler.json")
    
        asyncio.ensure_future(self.on_ready())
        
    async def on_ready(self):
        await self.bot.wait_until_ready()
        if("CommandRcon" not in self.bot.cogs):
            log.info("[module] 'CommandRcon' required, but not found in '{}'. Module unloaded".format(type(self).__name__))
            del self
            return
        self.CommandRcon = self.bot.cogs["CommandRcon"]

        
async def setup(bot):
    #await bot.add_cog(CommandRconTaskScheduler(bot))
    await bot.add_cog(CommandRconIngameComs(bot))