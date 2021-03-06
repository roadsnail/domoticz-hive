'''
<plugin key="HivePlug2" name="Hive Plugin2" author="imcfarla,MikeF & roadsnail" version="0.2" wikilink="http://www.domoticz.com/wiki/plugins/plugin.html" externallink="https://github.com/imcfarla2003/domoticz-hive">
    <params>
        <param field="Username" label="Hive Username" width="200px" required="true" default=""/>
        <param field="Password" label="Hive Password" width="200px" required="true" default=""/>
        <param field="Mode1" label="Heartbeat Multiplier" width="30px" required="true" default="6"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
'''
import Domoticz
import json
from urllib.parse import urlencode

class BasePlugin:
    enabled = False
    
    def __init__(self):
        self.sessionId = ''
        self.counter = 0
        self.multiplier = 10
        self.lightsSet = set()
        self.activeplugsSet = set()
        self.hwrelaySet = set()
        self.chrelaySet = set()
        self.TimedOutAvailable = True
        self.httpConn = False
        self.deviceConn = False
        self.sessionHost = 'beekeeper-uk.hivehome.com' 
        self.deviceHost = 'api.prod.bgchprod.info'
        self.deviceUpdate = False
        self.deviceUpdateConn = False
    
    def onStart(self):
        Domoticz.Log('Starting')
        if Parameters["Mode6"] == "Debug":
            Domoticz.Debugging(1)
        self.multiplier = int(Parameters['Mode1'])
        self.deviceUpdate = Buffer(10) # Buffer up to 10 commands
        if int(self.getDomoticzRevision()) < 9030: 
            Domoticz.Log("SNI connections are only available in Revision >= 9030.  This plugin will not work")
        else:    
            self.httpConn = Domoticz.Connection(Name="Hive Session", Transport="TCP/IP", Protocol="HTTPS", Address=self.sessionHost, Port="443")
            self.httpConn.Connect() # Get a SessionId
            self.deviceConn = Domoticz.Connection(Name="Hive Devices", Transport="TCP/IP", Protocol="HTTPS", Address=self.deviceHost, Port="443")
            self.deviceUpdateConn = Domoticz.Connection(Name="Hive Device Update", Transport="TCP/IP", Protocol="HTTPS", Address=self.deviceHost, Port="443")
 
    def onStop(self):
        Domoticz.Log('Deleting Session')
        return
        headers = {'Content-Type': 'application/vnd.alertme.zoo-6.1+json', 'Accept': 'application/vnd.alertme.zoo-6.2+json', \
        'X-AlertMe-Client': 'Hive Web Dashboard', 'X-Omnia-Access-Token': self.sessionId }
        url = 'https://api.prod.bgchprod.info:443/omnia/auth/sessions/' + self.sessionId
        req = Request(url, headers = headers)
        req.get_method = lambda : 'DELETE'
        try:
            r = urlopen(req).read()
        except Exception as e:
            Domoticz.Log(str(e))
    
    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug('onConnect called for ' + Connection.Name)
        if (Connection.Name == 'Hive Session'):
            if self.sessionId == '':
                Domoticz.Log('Creating Session')
                url = '/1.0/gateway/login'
                headers = {'Content-Type':'application/json', 'Accept':'application/json', 'Host':self.sessionHost}
                data = json.dumps({'username':Parameters["Username"],'password':Parameters["Password"]})
                Connection.Send({'Verb':'POST','URL':url,'Headers':headers,'Data':data})
        if (Connection.Name == 'Hive Devices'):
            Domoticz.Debug('Getting Devices')
            url = '/omnia/nodes'
            headers = {'Content-Type': 'application/vnd.alertme.zoo-6.2+json', 'Accept': 'application/vnd.alertme.zoo-6.2+json', \
                'X-AlertMe-Client': 'swagger', 'X-Omnia-Access-Token': self.sessionId, 'Host':self.deviceHost}
            Connection.Send({'Verb':'GET','URL':url,'Headers':headers})
        if (Connection.Name == 'Hive Device Update'):
            while (self.deviceUpdate.get_size() > 0):
                Domoticz.Debug('Updating Device')
                deviceUpdate = self.deviceUpdate.pop_element()
                self.updateDevice(deviceUpdate['Unit'],deviceUpdate['Command'],deviceUpdate['Level'],deviceUpdate['Hue'], Connection)
 
    def onMessage(self, Connection, Data):
        Domoticz.Debug('onMessage called for ' + Connection.Name)
        if (Connection.Name == 'Hive Session'):
            if (Data['Status'] == '200'):
                r = Data['Data'].decode('UTF-8')
                self.sessionId = json.loads(r)['token']
                Domoticz.Debug(self.sessionId)
                self.httpConn.Disconnect()
                self.deviceConn.Connect() # Update the devices now
        if (Connection.Name == 'Hive Devices'):
            if (Data['Status'] == '200'):
                r = Data['Data'].decode('UTF-8')
                nodes = json.loads(r)['nodes']
                self.deviceConn.Disconnect()
                self.ProcessDevices(nodes)
            else:
                # Bad session?
                self.httpConn.Connect()
        if (Connection.Name == 'Hive Device Update'):
            if (Data['Status'] == '200'):
                #if(self.deviceUpdate.get_size==0):
                    #self.deviceUpdateConn.Disconnect()
                self.deviceConn.Connect() # Update the devices now
            else:
                Domoticz.Error("Update Device Failed")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug('onCommand called for Unit ' + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))
        if(self.deviceUpdateConn.Connected()):
            self.updateDevice(Unit,Command,Level,Hue,self.deviceUpdateConn)
        else:
            self.deviceUpdate.push_element({'Unit':Unit,'Command':Command,'Level':Level,'Hue':Hue})
            if(self.deviceUpdateConn.Connecting() == False):
                self.deviceUpdateConn.Connect()

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug('Notification: ' + Name + ',' + Subject + ',' + Text + ',' + Status + ',' + str(Priority) + ',' + Sound + ',' + ImageFile)
    
    def onDisconnect(self, Connection):
        Domoticz.Debug('onDisconnect called')
    
    def onHeartbeat(self):
        Domoticz.Debug('onHeartbeat called')
        if self.counter >= self.multiplier:
            Domoticz.Debug('Getting Data')
            self.counter = 1
            self.deviceConn.Connect()
        else:
            self.counter += 1
            Domoticz.Debug('Counter = ' + str(self.counter))

    def ProcessDevices(self, d):
        foundInsideDevice = False
        foundTargetDevice = False
        foundHeatingDevice = False
        foundThermostatDevice = False
        foundHotWaterDevice = False
        
        Domoticz.Debug('Getting Temperatures')
        thermostat = self.GetThermostat(d, 'Heating')
        if thermostat:
            # get the temperature and heating states
            ch_id = thermostat["id"]	# Central Heating ID is same as Thermostat ID
            temp = thermostat["attributes"]["temperature"]["reportedValue"]
            Domoticz.Debug('Temp = ' + str(temp))
            targetTemp = thermostat["attributes"]["targetHeatTemperature"]["reportedValue"]
            if targetTemp < 7.0: targetTemp = 7.0
            Domoticz.Debug('Target = ' + str(targetTemp))
            heating = thermostat["attributes"]["stateHeatingRelay"]["reportedValue"]
            Domoticz.Debug('Heating = ' + heating)
            Domoticz.Debug('Getting Battery Status')
            thermostatui = self.GetThermostatUI(d)
            # get the battery and rssi values
            thermostat_battery = thermostatui["attributes"]["batteryLevel"]["reportedValue"]
            Domoticz.Debug('Battery = ' + str(thermostat_battery))
            thermostat_rssi = 12*((0 - thermostatui["attributes"]["RSSI"]["reportedValue"])/100)
            Domoticz.Debug('RSSI = ' + str(thermostat_rssi))
            # Loop through the devices and update temperatures
            Domoticz.Debug('Updating Devices')
            for unit in Devices:
                if Devices[unit].DeviceID == "Hive_Inside":
                    Devices[unit].Update(nValue=int(temp), sValue=str(temp))
                    foundInsideDevice = True
                if Devices[unit].DeviceID == "Hive_Target":
                    Devices[unit].Update(nValue=int(targetTemp), sValue=str(targetTemp))
                    foundTargetDevice = True
                if Devices[unit].DeviceID == ch_id and Devices[unit].Type == 244:	#if CH Switch device
                    foundHeatingDevice = True
                    if unit not in set(self.chrelaySet):
                        self.chrelaySet.add(unit)
                    if thermostatui["attributes"]["presence"]["reportedValue"] == "ABSENT":
                        if self.TimedOutAvailable:
                            if Devices[unit].TimedOut == 0:
                                Devices[unit].Update(nValue=Devices[unit].nValue, sValue=Devices[unit].sValue, TimedOut=1)
                        else:
                            Domoticz.Log("Device Offline : " + Devices[unit].Name)
                    else:
                        if heating == 'ON':
                            if Devices[unit].nValue == 0:
                                if self.TimedOutAvailable:
                                    Devices[unit].Update(nValue=1, sValue='On', TimedOut=0)
                                else:
                                    Devices[unit].Update(nValue=1, sValue='On')
                        else:
                            if Devices[unit].nValue == 1:
                                if self.TimedOutAvailable:
                                    Devices[unit].Update(nValue=0, sValue='Off', TimedOut=0)
                                else:
                                    Devices[unit].Update(nValue=0, sValue='Off')
                if Devices[unit].DeviceID == thermostat['id']:
                    foundThermostatDevice = True
                    if Devices[unit].Type == 242: #Thermostat
                       Devices[unit].Update(nValue = int(targetTemp), sValue = str(targetTemp), BatteryLevel = int(thermostat_battery), SignalLevel = int(thermostat_rssi)) 
            if foundInsideDevice == False:
                Domoticz.Device(Name = 'Inside', Unit = self.GetNextUnit(False), TypeName = 'Temperature', DeviceID = 'Hive_Inside').Create()
                self.counter = self.multiplier
            if foundTargetDevice == False:
                Domoticz.Device(Name = 'Target', Unit = self.GetNextUnit(False), TypeName = 'Temperature', DeviceID = 'Hive_Target').Create()
                self.counter = self.multiplier
            if foundHeatingDevice == False:
                Domoticz.Device(Name = 'Heating', Unit = self.GetNextUnit(False), TypeName = 'Switch', Switchtype = 0, DeviceID = ch_id).Create()
                self.counter = self.multiplier
            if foundThermostatDevice == False:
                Domoticz.Device(Name = 'Thermostat', Unit = self.GetNextUnit(False), Type = 242, Subtype = 1, DeviceID = thermostat['id']).Create()
                self.counter = self.multiplier
        else:
             Domoticz.Debug('No heating thermostat found')

        thermostatW = self.GetThermostat(d, 'HotWater')
        if thermostatW: # HotWater too...
            hotwater = thermostatW["attributes"]["stateHotWaterRelay"]["reportedValue"]
            Domoticz.Debug('Updating Devices')
            hw_id = thermostatW["id"]
            for unit in Devices:
                if Devices[unit].DeviceID == hw_id:
                    if unit not in set(self.hwrelaySet):
                        self.hwrelaySet.add(unit)
                    foundHotWaterDevice = True
                    if thermostatui["attributes"]["presence"]["reportedValue"] == "ABSENT":
                        if self.TimedOutAvailable:
                            if Devices[unit].TimedOut == 0:
                                Devices[unit].Update(nValue=Devices[unit].nValue, sValue=Devices[unit].sValue, TimedOut=1)
                        else:
                            Domoticz.Log("Device Offline : " + Devices[unit].Name)
                    else:
                        if hotwater == 'ON':
                            if Devices[unit].nValue == 0:
                                if self.TimedOutAvailable:
                                    Devices[unit].Update(nValue=1, sValue='On', TimedOut=0)
                                else:
                                    Devices[unit].Update(nValue=1, sValue='On')
                        else:
                            if Devices[unit].nValue == 1:
                                if self.TimedOutAvailable:
                                    Devices[unit].Update(nValue=0, sValue='Off', TimedOut=0)
                                else:
                                    Devices[unit].Update(nValue=0, sValue='Off')
            if foundHotWaterDevice == False:
                Domoticz.Device(Name = 'HotWater - Relay', Unit = self.GetNextUnit(False), TypeName = 'Switch', Switchtype = 0, DeviceID = hw_id).Create()
                self.counter = self.multiplier
        else:
             Domoticz.Debug('No hot water thermostat/relay found')

        lights = self.GetLights(d)
        if lights:
            for node in lights:
                for unit in Devices:
                    rssi = 12*((0 - node["attributes"]["RSSI"]["reportedValue"])/100)
                    if node['id'] == Devices[unit].DeviceID:
                        if unit not in set(self.lightsSet):
                            self.lightsSet.add(unit)
                        Domoticz.Debug(Devices[unit].Name + ": " + node["attributes"]["presence"]["reportedValue"])
                        if node["attributes"]["presence"]["reportedValue"] == "ABSENT":
                            if self.TimedOutAvailable:
                                if Devices[unit].TimedOut == 0:
                                    Devices[unit].Update(nValue=Devices[unit].nValue, sValue=Devices[unit].sValue, TimedOut=1, SignalLevel=0)
                            else:
                                Domoticz.Log("Device Offline : " + Devices[unit].Name)
                        else:
                            if node["attributes"]["state"]["reportedValue"] == "OFF":
                                if Devices[unit].nValue != 0:
                                    if self.TimedOutAvailable:
                                        Devices[unit].Update(nValue=0, sValue='Off', TimedOut=0, SignalLevel=int(rssi))
                                    else:
                                        Devices[unit].Update(nValue=0, sValue='Off', SignalLevel=int(rssi))
                            else:
                                Domoticz.Debug("State: " + Devices[unit].sValue)
                                Domoticz.Debug("Brightness Target: " + str(Devices[unit].LastLevel))
                                Domoticz.Debug("Brightness: " + str(node["attributes"]["brightness"]["reportedValue"]))
                                if Devices[unit].LastLevel != int(node["attributes"]["brightness"]["reportedValue"]) or Devices[unit].sValue == 'Off':
                                    if self.TimedOutAvailable:
                                        Devices[unit].Update(nValue=2, sValue=str(node["attributes"]["brightness"]["reportedValue"]), TimedOut=0, SignalLevel=int(rssi)) # 2 = Set Level
                                    else:
                                        Devices[unit].Update(nValue=2, sValue=str(node["attributes"]["brightness"]["reportedValue"]), SignalLevel=int(rssi)) # 2 = Set Level
                        break
                else:
                    Domoticz.Log("Light not found " + node["name"])
                    newUnit = self.GetNextUnit(False)
                    Domoticz.Device(Name = node["name"], Unit = newUnit, Type=244, Subtype=73, Switchtype=7, DeviceID = node['id']).Create()
                    #light_rssi = 12*((0 - node["attributes"]["RSSI"]["reportedValue"])/100)
                    if node["attributes"]["state"]["reportedValue"] == "OFF":
                        Devices[newUnit].Update(nValue=0, sValue='Off', SignalLevel=int(rssi))
                    else: 
                        Devices[newUnit].Update(nValue=2, sValue=str(node["attributes"]["brightness"]["reportedValue"]), SignalLevel=int(rssi)) # 2 = Set Level
        activeplugs = self.GetActivePlugs(d)
        if activeplugs:
            for node in activeplugs:
                for unit in Devices:
                    rssi = 12*((0 - node["attributes"]["RSSI"]["reportedValue"])/100)
                    if node['id'] == Devices[unit].DeviceID:
                        if unit not in set(self.activeplugsSet):
                            self.activeplugsSet.add(unit)
                        if node["attributes"]["presence"]["reportedValue"] == "ABSENT":
                            if self.TimedOutAvailable:
                                if Devices[unit].TimedOut == 0:
                                    Devices[unit].Update(nValue=Devices[unit].nValue, sValue=Devices[unit].sValue, TimedOut=1, SignalLevel=0)
                            else:
                                Domoticz.Log("Device Offline : " + Devices[unit].Name)
                        else:
                            if node["attributes"]["state"]["reportedValue"] == "OFF":
                                if Devices[unit].nValue != 0:
                                    if self.TimedOutAvailable:
                                        Devices[unit].Update(nValue=0, sValue='Off', TimedOut=0, SignalLevel=int(rssi))
                                    else:
                                        Devices[unit].Update(nValue=0, sValue='Off', SignalLevel=int(rssi))
                            else:
                                Domoticz.Debug("State: " + Devices[unit].sValue)
                                if Devices[unit].nValue != 1:
                                    if self.TimedOutAvailable:
                                        Devices[unit].Update(nValue=1, sValue='On', TimedOut=0, SignalLevel=int(rssi))
                                    else:
                                        Devices[unit].Update(nValue=1, sValue='On', SignalLevel=int(rssi))
                        break
                else:
                    Domoticz.Log("ActivePlug not found " + node["name"])
                    newUnit = self.GetNextUnit(False)
                    Domoticz.Device(Name = node["name"], Unit = newUnit, Type=244, Subtype=73, Switchtype=0, DeviceID = node['id']).Create()
                    if node["attributes"]["state"]["reportedValue"] == "OFF":
                        Devices[newUnit].Update(nValue=0, sValue='Off', SignalLevel=int(rssi))
                    else:
                        Devices[unit].Update(nValue=1, sValue='On', SignalLevel=int(rssi))

    def updateDevice(self, Unit, Command, Level, Hue, Connection):
        Domoticz.Debug('updateDevice called for Unit ' + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))
        Domoticz.Debug(str(Devices[Unit].Type))
        Domoticz.Debug(str(Devices[Unit].SubType))
        Domoticz.Debug(Devices[Unit].DeviceID)
        Domoticz.Debug(str(Devices[Unit].sValue))
        headers = {'Content-Type': 'application/vnd.alertme.zoo-6.2+json', 'Accept': 'application/vnd.alertme.zoo-6.2+json', \
            'X-AlertMe-Client': 'swagger', 'X-Omnia-Access-Token': self.sessionId, 'Host':self.deviceHost}
        url = '/omnia/nodes/' + Devices[Unit].DeviceID
        payload = ""
        if self.isLight(Unit):
            Domoticz.Log("Setting Light Parameters")
            if str(Command) == "Set Level":
                payload = self.CreateLightPayload("ON", Level)
            if str(Command) == "On":
                payload = self.CreateLightPayload("ON", Devices[Unit].LastLevel)
            if str(Command) == "Off":
                payload = self.CreateLightPayload("OFF", Devices[Unit].LastLevel)
        elif self.isThermostat(Unit):
            Domoticz.Log("Setting Thermostat Level")
            payload = self.CreateThermostatPayload(Level)
        elif self.isActivePlug(Unit):
            Domoticz.Log("Setting ActivePlug State")
            if str(Command) == "On":
                payload = self.CreateActivePlugPayload("ON")
            if str (Command) == "Off":
                payload = self.CreateActivePlugPayload("OFF") 
        elif self.isHotWaterRelay(Unit):
            Domoticz.Log("Setting Hot Water Relay State")
            if str(Command) == "On":
                payload = self.CreateHotWaterPayload("HEAT") # Android APP Shows as On
            if str(Command) == "Off":
                payload = self.CreateHotWaterPayload("OFF") # Android APP shows as Off
        elif self.isCentralHeatingRelay(Unit):
            Domoticz.Log("Setting Central Heating Relay State")
            if str(Command) == "On":
                payload = self.CreateCentralHeatingPayload("HEAT") # Android APP Shows as Manual (Governed by Thermostat setting)
            if str(Command) == "Off":
                payload = self.CreateCentralHeatingPayload("OFF") # Android APP shows as Off
        else:
            payload = ""
            Domoticz.Log("Unknown Device Type")
        if payload != "":
            data = json.dumps(payload)
            Connection.Send({'Verb':'PUT','URL':url,'Headers':headers,'Data':data})
    
    def GetThermostat(self, d, ttype):
        #ttype can be 'Heating' or 'HotWater'
        thermostat = False
        k = 'state'+ttype+'Relay'
        x = find_key_in_list(d, 'http://alertme.com/schema/json/node.class.thermostat.json#')
        if x:
            for i in x:
                if k in i['attributes']:
                    thermostat = i
        return thermostat

    def GetThermostatUI(self, d):
        thermostatui = False
        x = find_key_in_list(d, 'http://alertme.com/schema/json/node.class.thermostatui.json#')
        if x:
            thermostatui = x[0]
        else: # Try a Hive2 thermostat
            x = find_key_in_list(d,"Hive2")
            if x:
                thermostatui = x[0]
        return thermostatui

    def GetLights(self, d):
        lights = False
        x = find_key_in_list(d,"http://alertme.com/schema/json/node.class.light.json#")
        if x:
            lights = x
        return lights

    def GetActivePlugs(self, d):
        activeplugs = False
        x = find_key_in_list(d,"http://alertme.com/schema/json/node.class.smartplug.json#")
        if x:
            activeplugs = x
        return activeplugs

    def GetNextUnit(self, unit):
        if not unit:
            nextUnit = len(Devices) + 1
        else:
            nextUnit = unit +1
        if nextUnit in Devices or nextUnit <= 1:
            nextUnit = self.GetNextUnit(nextUnit)
        return nextUnit

    def CreateLightPayload(self, State, Brightness):
        response = {}
        nodes = []
        attributes = {}
        state = {}
        brightness = {}
        brightness["targetValue"] = Brightness
        state["targetValue"] = State
        attributes["attributes"] = {"brightness":brightness,"state":state}
        nodes.append(attributes)
        response["nodes"] = nodes
        return response

    def CreateThermostatPayload(self, Temperature):
        response = {}
        nodes = []
        attributes = {}
        targetHeatTemperature = {}
        targetHeatTemperature["targetValue"] = Temperature
        attributes["attributes"] = {"targetHeatTemperature":targetHeatTemperature}
        nodes.append(attributes)
        response["nodes"] = nodes
        return response

    def CreateActivePlugPayload(self, State):
        response = {}
        nodes = []
        attributes = {}
        state = {}
        state["targetValue"] = State
        attributes["attributes"] = {"state":state}
        nodes.append(attributes)
        response["nodes"] = nodes
        return response

    def CreateHotWaterPayload(self, State):
        response = {}
        nodes = []
        attributes = {}
        if State == "HEAT":
            Domoticz.Debug('HW On')
            attributes["attributes"] = {"activeHeatCoolMode": {"targetValue": "HEAT"},"activeScheduleLock": {"targetValue": "True"}}
        if State == "OFF":
            Domoticz.Debug('HW Off')
            attributes["attributes"] = {"activeHeatCoolMode": {"targetValue": "OFF"},"activeScheduleLock": {"targetValue": "False"}}
        nodes.append(attributes)
        response["nodes"] = nodes
        return response

    def CreateCentralHeatingPayload(self, State):
        response = {}
        nodes = []
        attributes = {}
        if State == "HEAT":
            Domoticz.Debug('CH On')
            attributes["attributes"] = {"activeHeatCoolMode": {"targetValue": "HEAT"},"activeScheduleLock": {"targetValue": "True"}}
        if State == "OFF":
            Domoticz.Debug('CH Off')
            attributes["attributes"] = {"activeHeatCoolMode": {"targetValue": "OFF"},"activeScheduleLock": {"targetValue": "False"}}
        nodes.append(attributes)
        response["nodes"] = nodes
        return response    

    def isLight(self, Unit):
        Domoticz.Debug(str(self.lightsSet))
        if Devices[Unit].Type == 244 and Devices[Unit].SubType == 73 and Unit in self.lightsSet:
            return True
        else:
            return False

    def isThermostat(self, Unit):
        if Devices[Unit].Type == 242:
            return True
        else:
            return False

    def isActivePlug(self, Unit):
        if Devices[Unit].Type == 244 and Devices[Unit].SubType == 73 and Unit in self.activeplugsSet:
            return True
        else:
            return False

    def isHotWaterRelay(self, Unit):
        if Unit in self.hwrelaySet:
            return True
        else:
            return False

    def isCentralHeatingRelay(self, Unit):
        Domoticz.Debug(str(self.chrelaySet))
        if Unit in self.chrelaySet:
            return True
        else:
            return False

    def getDomoticzRevision(self):
        Revision = 8650 #Min version that supports all the features required -1
        if 'DomoticzVersion' in Parameters:
            Domoticz.Log("DomoticzVersion Available")
            Revision = Parameters['DomoticzVersion'][-4:]
        Domoticz.Debug("Domoticz Revision: " + str(Revision))
        return Revision

_plugin = BasePlugin()

def onStart():
    _plugin.onStart()

def onStop():
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    _plugin.onHeartbeat()

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != '':
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug('Device count: ' + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug('Device:           ' + str(x) + ' - ' + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug('Device nValue:    ' + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug('Device LastLevel: ' + str(Devices[x].LastLevel))

def DumpHTTPResponseToLog(httpDict):
    if isinstance(httpDict, dict):
        Domoticz.Log("HTTP Details ("+str(len(httpDict))+"):")
        for x in httpDict:
            if isinstance(httpDict[x], dict):
                Domoticz.Log("--->'"+x+" ("+str(len(httpDict[x]))+"):")
                for y in httpDict[x]:
                    Domoticz.Log("------->'" + y + "':'" + str(httpDict[x][y]) + "'")
            else:
                Domoticz.Log("--->'" + x + "':'" + str(httpDict[x]) + "'")

def find_key_in_list(d, value):
    if isinstance(d, list):
        t = list(d)
        for v in d:
            if isinstance(v, dict):
                p = find_key(v, value)
                if not p:
                    t.remove(v)
        return t

def find_key(d, value):
    for (k, v) in d.items():
        if isinstance(v, dict):
            p = find_key(v, value)
            if p:
                return [k] + p
        elif v == value:
            return [k]
    
def merge_dicts(*dict_args):
    '''
    Given any number of dicts, shallow copy and merge into a new dict,
    precedence goes to key value pairs in latter dicts.
    '''
    result = { }
    for dictionary in dict_args:
        result.update(dictionary)
    return result

class Buffer:
    def __init__(self, capacity):
        self.buffer = [0] * capacity
        self.size = 0
        self.capacity = capacity
        self.head_index = 0
        self.tail_index = 0

    def push_element(self, value):
        if self.size == self.capacity:
            raise Exception('The buffer is full.')
        self.buffer[self.tail_index] = value
        self.tail_index = (self.tail_index + 1) % self.capacity
        self.size += 1
        Domoticz.Log("Buffer Size: "+str(self.size))
    
    def pop_element(self):
        if self.size == 0:
            raise Exception('Popping from an empty buffer.')
        ret = self.buffer[self.head_index]
        self.head_index = (self.head_index + 1) % self.capacity
        self.size -= 1
        Domoticz.Log("Buffer Size: "+str(self.size))
        return ret

    def peek_head(self):
        if self.size == 0:
            raise Exception('Peeking into an empty buffer.')
        return self.buffer[self.head_index]

    def peek_tail(self):
        if self.size == 0:
            raise Exception('Peeking into an empty buffer.')
        return self.buffer[self.tail_index]

    def get_size(self):
        return self.size

# vim: tabstop=4 expandtab

