#pip install matplotlib

import matplotlib.pyplot as plt
import ast
import os
from datetime import datetime
import json
import re


from collections import deque
import traceback
import sys
import itertools
import asyncio
import inspect
from modules.core.utils import Event_Handler
from modules.core.Log import log
import psutil

from func_timeout import func_timeout, FunctionTimedOut

class ProcessLog:
    def __init__(self, readLog, cfg_jmw):
        self.readLog = readLog
        self.path = os.path.dirname(os.path.realpath(__file__))
        self.cfg_jmw = cfg_jmw
        
        self.databuilder = {}
        #self.active = False

        self.define_EH()
        self.EH.disabled = True
        
        #Add EventHandlers:
        #self.readLog.EH.add_Event("Mission script error", self.missionError)
        
        #self.readLog.pre_scan()
        #self.active = True
        asyncio.ensure_future(self._system_res())
        
        
    async def _system_res(self):
        try:
            self.system_res = deque(maxlen=1440*10) #1440 = 1 day
            while True:
                databuilder = {}
                databuilder["cpu"] = round(psutil.cpu_percent(),2)
                databuilder["ram"] = round(psutil.virtual_memory().percent,2)
                databuilder["swap"] = round(psutil.swap_memory().percent,2)
                databuilder["time"] = str(datetime.now().strftime("%Y-%m-%d %H-%M-%S"))
                self.system_res.append(databuilder)
                await asyncio.sleep(60)
        except Exception as e:
            log.error(e)
            
    def define_EH(self):
        self.events = [
            "on_missionHeader",
            "on_missionGameOver",
            "on_missionData"
        ]
        
        self.EH = Event_Handler(self.events)
        
    def missionError(*args):
        log.info(args)
        
    def processGameData(self, pdata):
        data = pdata.copy()
        last_time = 0
        last_time_iter = 0
        first_line = True
        set_new = False     #when game crashed and mission continues
        #created_df = False
        #values
        meta = {
                "map": "Unkown",
                "winner": "currentGame",
                "timestamp": str(datetime.now().strftime("%H-%M-%S")),
                "date": str(datetime.now().strftime("%Y-%m-%d")) #TODO get log date
        }
        for val in data:
            if(val["CTI_DataPacket"]=="Header"):
                if(first_line==False):
                    set_new = True   
                meta["map"] = val["Map"]
                
            if(val["CTI_DataPacket"]=="Data"):
                if(set_new == True):
                    set_new = False
                    last_time = last_time_iter

                val["time"] = val["time"]+last_time
                last_time_iter = val["time"] 
                #if(val["time"] > 100000 and created_df == False):
                #    log.info("[WARNING] Data timeframe out of bounds: {}".format(val))
                #    with open('dataframe.json', 'a+') as outfile:
                #        json.dump(data, outfile)
                #    created_df = True
            if(val["CTI_DataPacket"]=="GameOver"):
                meta["timestamp"] = val["timestamp"]
                #meta["map"] = val["Map"]
                if(val["Lost"]):
                    if(val["Side"] == "WEST"):
                        meta["winner"] = "EAST"
                    else:
                        meta["winner"] = "WEST"
                else:
                    if(val["Side"] == "WEST"):
                        meta["winner"] = "WEST"
                    else:
                        meta["winner"] = "EAST"  
                last_time = 0
                last_time_iter = 0
            first_line = False
        return [meta, data]
    
    #might fail needs try catch
    #uses recent data entries to create a full game
    def readData(self, admin, gameindex):
        meta, game, dict = self.generateGame(gameindex)
        return self.dataToGraph(meta, game, admin, gameindex)

    # helper function
    def generateGame(self, gameindex=None):
        return func_timeout(10, self._generateGame, args=[gameindex])
            
    #generates a game from recent entries    
    # index: 0 = current game
    def _generateGame(self, gameindex=None):
        if(gameindex == None):
            gameindex = 0
        log.info("Generating Game, index: '{}'".format(gameindex))
        game = self.buildGameBlock(gameindex)
        dict, game = self.processGameBlock(game)
        meta, pdata = self.processGameData(game)
        return [meta, pdata, dict]

        

    def updateDicArray(self, parent, data):
        if("players" in parent and "players" in data):
            parent["CTI_DataPacket"] = data["CTI_DataPacket"]
            parent["players"] = parent["players"]+data["players"]
            return parent
        parent.update(data)
        return parent

    # Conforms a log line array (string) into a valid Python dict
    def parseLine(self, msg):
        r = msg.rstrip() #remove /n
        #converting arma3 boolen working with python +converting rawnames to strings:#
        #(?<!^|\]|\[)"(?!\]|\[$)
        #(?:^(?<!\])|(?<!\[))"(?:(?!\])|\[)
        r = r.replace('\\', '') #Filter possible escape chars
        r = re.sub(r'(?:^(?<!\])|(?<!\[|,))"(?:(?!\]|,))', "'", r) #removes invalid qoutes
        r = r.replace('""', ',"WEST"]')
        r = r.replace(",WEST]", ',"WEST"]')
        r = r.replace(",EAST]", ',"EAST"]') #this still needs working
        r = r.replace("true", "True")
        r = r.replace("false", "False")
        data = ast.literal_eval(r) #WARNING: Security risk
        #log.info(data)
        return dict(data)

    def buildGameBlock(self, index=0):
        current_index = 0
        iterMission = iter(reversed(self.readLog.Missions))
        try:
            for i in range(self.readLog.maxMissions):
                game = None
                #Get a Valid game block
                while game == None:
                    new_game = next(iterMission)
                    if("Mission id" in new_game["dict"]):
                        game = new_game # Get most recent mission start
                        game["crashed"] = 0
                        
                for mission in iterMission:
                    if("Mission finished" in mission["dict"]):
                        break
                    elif("Mission id" in mission["dict"] and game["dict"]["Mission readname"] == mission["dict"]["Mission readname"] and game["dict"]["Mission world"] == mission["dict"]["Mission world"]):
                        game["crashed"] += 1
                        game["dict"].update(mission["dict"])
                if(current_index == index):
                    return game
                current_index += 1
        except StopIteration:
            pass
        raise IndexError("index '{}' OutofBounds for games with len({})".format(index, current_index-1))

    def processGameBlock(self, game):
        processed_game = []
        for line in game["data"]:
            data = self.processLogLine(*line[:2])
            if(data):
                processed_game.append(data)
        return game["dict"], processed_game

    def processLogLine(self, timestamp, line):
        #check if line contains a datapacket
        m = re.match('^(\[\["CTI_DataPacket","(.*?)"],.*])', line)
        if(m):
            type = m.group(2)
            try:
                datarow = self.parseLine(line) #convert string into array object
                if(type == "Header"):
                    datarow["timestamp"] = timestamp
                    return datarow
                elif("Data_" in type):
                    index = int(re.match('.*_([0-9]*)', type).group(1))
                    if(len(self.databuilder)>0):
                        index_db = int(re.match('.*_([0-9]*)', self.databuilder["CTI_DataPacket"]).group(1))
                        #check if previous 'Data_x' is present
                        if(index_db+1 == index):
                            self.databuilder = self.updateDicArray(self.databuilder, datarow)
                            #If last element "Data_EOD" is present, 
                            if("EOD" in type):
                                self.databuilder["CTI_DataPacket"] = "Data"
                                datarow = self.databuilder.copy()
                                self.databuilder = {}
                                return datarow
                    elif(type == "Data_1"):
                        #add first element
                        self.databuilder = self.updateDicArray(self.databuilder, datarow)

                elif(type == "EOF"):
                    pass
                    #raise Exception("Read mission EOF")
                    #return datarow #return EOF (should usually never be called)
                elif(type == "GameOver"):
                    datarow["timestamp"] = timestamp #finish time
                    return datarow #return Gameover / End
                
            except Exception as e:
                log.error(e)
                log.info(line)
                log.print_exc()
        #return self.databuilder
                
   
###################################################################################################
#####                                  Graph Generation                                        ####
###################################################################################################   

    def featchValues(self, data,field):
        list = []
        for item in data:
            if(field in item):
                list.append(item[field])
            else:
                list.append(0)
        return list[:-1]   

    def featchValuesDeque(self, data, field, slice_lenght):
        list = []
        start = len(data)-slice_lenght 
        if start < 0:
            start = 0
        for i in range(start, len(data)):
            if(field in data[i]):
                list.append(data[i][field])
            else:
                list.append(0)
        dif = abs(len(list) - slice_lenght)
        if(dif != 0):
            list = ([0] * dif) + list
        return list[:-1]
   
        
    def dataToGraph(self, meta, data, admin, index=0):
        system_res = self.system_res
        lastwinner = meta["winner"]
        lastmap = meta["map"]
        timestamp = meta["timestamp"]
        e = len(data)
        loadedFromFile = False
        if(timestamp == None):
            timestamp = "00:00:00"
        else:
            t = []
            for block in timestamp.split(":"):
                if len(block)==1:
                    t.append("0"+block)
                else:
                    t.append(block)
            timestamp = ":".join(t)
        fdate = meta["date"]
        
        
        #Calculate time in min
        time = self.featchValues(data, "time")
        for i in range(len(time)):
            if(time[i] > 0):
                time[i] = time[i]/60 #seconds->min
        
        if (len(time) > 0):
            if(round(time[-1]) == 0):
                gameduration = round(time[-2])
            else:
                gameduration = round(time[-1])
        else:
            gameduration = 0
        log.info("{} {} {}".format(timestamp, lastwinner, gameduration))
        
        
        
        t=""
        if(lastwinner=="currentGame"):
            t = "-CUR"
        if(admin==True):
            t +="-ADV"
        #path / date # time # duration # winner # addtional_tags
        filename_pic =(self.cfg_jmw['image_path']+fdate+"#"+timestamp.replace(":","-")+"#"+str(gameduration)+"#"+lastwinner+"#"+lastmap+"#"+t+'.png').replace("\\","/")
        filename =    (self.cfg_jmw['data_path']+ fdate+"#"+timestamp.replace(":","-")+"#"+str(gameduration)+"#"+lastwinner+"#"+lastmap+"#"+t+'.json').replace("\\","/")
        
        
        if(os.path.isfile(filename)):
            with open(filename) as json_file:
                data = json.load(json_file)
                #system_res = data["sys"] --> Doesnt work due to matched format
                loadedFromFile = True
        #register plots
        plots = []
        v1 = self.featchValues(data, "score_east")
        v2 = self.featchValues(data, "score_west")
        #data: [[data, color_String],....]
        if(len(v1) > 0):
            plots.append({
                "data": [[v1, "r"],
                        [v2, "b"]],
                "xlabel": "Time in min",
                "ylabel": "Team Score",
                "title": "Team Score"
                })
     
        v1 = self.featchValues(data, "town_count_east")
        v2 = self.featchValues(data, "town_count_west")
        if(len(v1) > 0):
            plots.append({
                "data": [[v1, "r"],
                        [v2, "b"]],
                "xlabel": "Time in min",
                "ylabel": "Towns owned",
                "title": "Towns owned"
                })
                
        v1 = self.featchValues(data, "player_count_east")
        v2 = self.featchValues(data, "player_count_west")
        if(len(v1) > 0):
            plots.append({
                "data": [[v1, "r"],
                        [v2, "b"]],
                "xlabel": "Time in min",
                "ylabel": "Players",
                "title": "Players on Server"
                })  
                
        if(admin == True):
            v1 = self.featchValues(data, "fps")
            if(len(v1) > 0):
                v1[0] = 60
                v1[1] = 0
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "Server FPS",
                    "title": "Server FPS",
                    "autoscaley_on": False,
                    "ylim": (0, 60)
                    }) 
                    
        if(admin == True):       
            v1 = self.featchValues(data, "active_SQF_count")
            if(len(v1) > 0):
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "active SQF",
                    "title": "active Server SQF"
                    })  
                    
        if(admin == True):       
            v1 = self.featchValues(data, "active_towns")
            if(len(v1) > 0):
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "active Towns",
                    "title": "active Towns"
                    }) 
                    
        if(admin == True):       
            v1 = self.featchValues(data, "active_AI")
            if(len(v1) > 0):
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "Units",
                    "title": "Total Playable units count"
                    })  
                    
        if(admin == True):       
            v1 = self.featchValues(data, "total_objects")
            if(len(v1) > 0):
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "Objects",
                    "title": "Total Objects count"
                    })  
        if(admin == True and (loadedFromFile == True or index==0)):       
            v1 = self.featchValuesDeque(system_res, "cpu", e)
            if(len(v1) > 0):
                v1[0] = 100
                v1[1] = 0
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "usage in %",
                    "title": "Total CPU usage",
                    "autoscaley_on": False,
                    "ylim": (0, 100)
                    })  
        if(admin == True and (loadedFromFile == True or index==0)):       
            v1 = self.featchValuesDeque(system_res, "ram", e)
            if(len(v1) > 0):
                v1[0] = 100
                v1[1] = 0
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "usage in %",
                    "title": "Total RAM usage",
                    "autoscaley_on": False,
                    "ylim": (0, 100)
                    })       
        if(admin == True and (loadedFromFile == True or index==0)):       
            v1 = self.featchValuesDeque(system_res, "swap", e)
            if(len(v1) > 0):
                v1[0] = 100
                v1[1] = 0
                plots.append({
                    "data": [[v1, "g"]],
                    "xlabel": "Time in min",
                    "ylabel": "usage in %",
                    "title": "Total SWAP usage",
                    "autoscaley_on": False,
                    "ylim": (0, 100)
                    })  

        
        #maps plot count to image size
        #plot_count: image_size
        hight={ 12: 22,
                11: 22,
                10: 18,
                9: 18,
                8: 14,
                7: 14,
                6: 10,
                5: 10,
                4: 6,
                3: 6,
                2: 3,
                1: 3}
        phight = 10
        if(len(plots) in hight):
            phight = hight[len(plots)]
        fig = plt.figure(figsize = (10,phight)) 

        fig.suptitle("Game end: "+fdate+" "+timestamp+", "+str(gameduration)+"min. Map: "+lastmap+" Winner: "+lastwinner, fontsize=14)
        #red_patch = mpatches.Patch(color='red', label='The red data')
        #plt.legend(bbox_to_anchor=(0, 0), handles=[red_patch])
        fig.subplots_adjust(hspace=0.3)
        zplots = []
        #writes data to plot
        for pdata in plots:
            if(len(pdata["data"][0])>0):
                zplots.append(fig.add_subplot( int(round((len(plots)+1)/2)), 2 ,len(zplots)+1))
                for row in pdata["data"]:
                    zplots[-1].plot(time, row[0], color=row[1])
                zplots[-1].grid(True, lw = 1, ls = '-', c = '.75')
                zplots[-1].set_xlabel(pdata["xlabel"])
                zplots[-1].set_ylabel(pdata["ylabel"])
                zplots[-1].set_title(pdata["title"])
        
        #create folders to for images / raw data
        if not os.path.exists(self.cfg_jmw['data_path']):
            os.makedirs(self.cfg_jmw['data_path'])
        if not os.path.exists(self.cfg_jmw['image_path']):
            os.makedirs(self.cfg_jmw['image_path'])
        
        # match sys res to mission data:
        # if is game just finished:
        try:
            if(lastwinner!="currentGame" and index==0):
                for i in range(1, len(data)):
                    data[-i]["sys"] = self.system_res[-i]
        except IndexError:
            pass
            
        #save image
        if(not os.path.isfile(filename_pic)):
            fig.savefig(filename_pic, dpi=100, pad_inches=3)
        #fig.gcf()
        plt.close('all')
        #save rawdata
        if(not os.path.isfile(filename)):
            with open(filename, 'w') as outfile:
                json.dump(data, outfile)
        
        return {"date": fdate, "time": timestamp, "lastwinner": lastwinner, "gameduration": gameduration, "picname": filename_pic, "dataname": filename, "data": data}


