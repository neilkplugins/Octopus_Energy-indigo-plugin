#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2020 neilk
#
# Based on the sample dimmer plugin and various vehicle plugins for Indigo
# Uses the jlrpy Library from https://github.com/ardevd/jlrpy converted to python 2

################################################################################
# Imports
################################################################################
import indigo
import requests
import json
import time
import datetime 

################################################################################
# Globals
################################################################################
# The base URL for the Octopus Energy API
BASE_URL = "https://api.octopus.energy/v1"
# GSP is Grid Supply point, it is generated from a postcode and used to select the correct tariff for the location
# this is the api call to return the GSP when the postcode is entered
GET_GSP = "/industry/grid-supply-points/?postcode="
# This is the product code for the Octopus Energy Agile Tariff which will return the 30 min rates when combined with a GSP
PRODUCT_CODE="AGILE-18-02-21"
# This is the upper rate cap for Agile Octopus, presumably this could change but it is currently not in the API
# Maybe this should be a plugin config option, but if it doesn't change often then it adds complexity
CAPPED_RATE = 35


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    # Class properties
    ########################################

    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        super(Plugin, self).__init__(pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
        self.debug = pluginPrefs.get("showDebugInfo", False)
        self.deviceList = []


    ########################################
    def deviceStartComm(self, device):
        self.debugLog("Starting device: " + device.name)
        self.debugLog(str(device.id)+ " " + device.name)
        device.stateListOrDisplayStateIdChanged()
        if device.id not in self.deviceList:
            self.update(device)
            self.deviceList.append(device.id)



    ########################################
    def deviceStopComm(self, device):
        self.debugLog("Stopping device: " + device.name)
        if device.id in self.deviceList:
            self.deviceList.remove(device.id)

    ########################################
    def runConcurrentThread(self):
        self.debugLog("Starting concurrent thread")
        pollingFreq = int(self.pluginPrefs['pollingFrequency'])
        try:
            while True:
                # we sleep (by a user defined amount, default 60s) first because when the plugin starts, each device
                # is updated as they are started.
                self.sleep(1 * pollingFreq )
                self.debugLog(self.deviceList)
                for deviceId in self.deviceList:
                    # call the update method with the device instance
                    self.update(indigo.devices[deviceId])
        except self.StopThread:
            pass

    ########################################
    def update(self,device):
    	TARIFF_CODE="E-1R-"+PRODUCT_CODE+"-"+self.pluginPrefs['gsp']
    	utctoday =datetime.datetime.utcnow().date()
    	PERIOD="period_from="+str(utctoday)+"T00:00Z&period_to="+str(utctoday)+"T23:59Z"
    	self.debugLog(PERIOD)
    	GET_LOCAL_TARIFFS = BASE_URL+"/products/"+PRODUCT_CODE+"/electricity-tariffs/"+TARIFF_CODE+"/standard-unit-rates/?"+PERIOD
    	try:
    		response = requests.get(GET_LOCAL_TARIFFS, timeout=1)
    		response.raise_for_status()
    	except requests.exceptions.HTTPError as err:
    		self.debugLog("Http Error "+ str(err))
    	except Exception as err:
    		self.debugLog("Other error"+str(err))
    	# else:
#     		self.debugLog("Connected to Octopus Servers")
    	if response.status_code ==200:
    		results_json = response.json()
    		#self.debugLog(results_json)
    		half_hourly_rates = results_json['results']
    		#self.debugLog(half_hourly_rates)
    	else:
    		self.debugLog("Error in getting current tariffs")
    	now = datetime.datetime.utcnow()
    	if int(now.strftime("%M")) > 29:
    		current_tariff_valid_period = (now.strftime("%Y-%m-%dT%H:30:00Z"))
    		self.debugLog("second half "+current_tariff_valid_period)
    	else:
    		current_tariff_valid_period = (now.strftime("%Y-%m-%dT%H:00:00Z"))
    	sum = 0
    	max = 0
    	# This is the current rate cap for Agile Octopus, min value should always be lower than this
    	min = CAPPED_RATE
    	for rates in half_hourly_rates:
    		sum = sum + rates["value_inc_vat"]
    		if rates["value_inc_vat"] >= max:
    			max = rates["value_inc_vat"]
    		if rates["value_inc_vat"] <= min:
    			min = rates["value_inc_vat"]
    		if rates['valid_from'] == current_tariff_valid_period:
    			self.debugLog("Current Rate inc vat is "+str(rates["value_inc_vat"]))
    			current_tariff = float(rates["value_inc_vat"])
    	average_rate = sum / results_json['count']
    	device.updateStateOnServer('Current_Electricity_Rate',current_tariff, uiValue=str(current_tariff)+"p")
    	device.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)
    	device.updateStateOnServer('Daily_Average_Rate',average_rate, decimalPlaces=4)
    	device.updateStateOnServer('Daily_Max_Rate',max, decimalPlaces=4)
    	device.updateStateOnServer('Daily_Min_Rate',min, decimalPlaces=4)
    	GET_STANDING_CHARGES = BASE_URL+"/products/"+PRODUCT_CODE+"/electricity-tariffs/"+TARIFF_CODE+"/standing-charges/"
    	try:
    		response = requests.get(GET_STANDING_CHARGES, timeout=1)
    		response.raise_for_status()
    	except requests.exceptions.HTTPError as err:
    		self.debugLog("Http Error "+ str(err))
    	except Exception as err:
    		self.debugLog("Other error"+err)
    	if response.status_code ==200:
    		standing_charge_json = response.json()
    		standing_charge_inc_vat = float(standing_charge_json["results"][0]["value_inc_vat"])
    		self.debugLog("Standard Charge "+str(standing_charge_inc_vat))
    	else:
    		self.debugLog("Error getting Standard Charges")
    	device.updateStateOnServer('Daily_Standing_Charge',standing_charge_inc_vat, uiValue=str(standing_charge_inc_vat)+"p")
    	device.updateStateOnServer('deviceLastUpdated',str(datetime.datetime.now()))
    	return()


    

	
    ########################################
    # UI Validate, Plugin Preferences
    ########################################
    def validatePrefsConfigUi(self, valuesDict):
        if not(valuesDict['Postcode']):
        	self.errorLog("Postcode Cannot Be Empty")
        	errorsDict = indigo.Dict()
        	errorsDict['Postcode'] = "Postcode Cannot Be Empty"
        	return (False, valuesDict, errorsDict)
    	
    
        
        try:
        	response = requests.get(BASE_URL+GET_GSP+valuesDict['Postcode'], timeout=1)
    		response.raise_for_status()
    	except requests.exceptions.HTTPError as err:
    		
    		self.debugLog("Http Error "+ str(err))
    		errorsDict = indigo.Dict()
        	errorsDict['Postcode'] = "Error validating with Octopus"
        	return (False, valuesDict, errorsDict)
    	except Exception as err:
    		self.debugLog("Other error"+err)
    		errorsDict = indigo.Dict()
        	errorsDict['Postcode'] = "Error validating with Octopus"
        	return (False, valuesDict, errorsDict)
    	else:
    		self.debugLog("Connected to Octopus Servers")
    	if response.status_code ==200:
    		gsp_json =  response.json()
    		if gsp_json['count']==0:
        		self.debugLog("GSP Not returned")
        		errorsDict = indigo.Dict()
        		errorsDict['Postcode'] = "GSP Not returned - Check Postcode"
        		return (False, valuesDict, errorsDict)
    		else:
        		gsp= gsp_json['results'][0]['group_id'][1]
        		self.debugLog("GSP is "+gsp)
        		self.pluginPrefs['gsp'] = gsp
        else:
    		gsp = "Unknown API Error"
    		self.debugLog(response)
    		errorsDict = indigo.Dict()
        	errorsDict['Postcode'] = "Unknown Octopus API Error"
        	return (False, valuesDict, errorsDict)
        try:
        	timeoutint=float(valuesDict['requeststimeout'])
        except:
            self.errorLog("Invalid entry for  API Timeout - must be a number")
            errorsDict = indigo.Dict()
            errorsDict['requeststimeout'] = "Invalid entry for API Timeout - must be a number"
            return (False, valuesDict, errorsDict)
        try:
            pollingfreq = int(valuesDict['pollingFrequency'])
        except:
            self.errorLog("Invalid entry for Polling Frequency - must be a whole number greater than 0")
            errorsDict = indigo.Dict()
            errorsDict['pollingFrequency'] = "Invalid entry for Polling Frequency - must be a whole number greater than 0"
            return (False, valuesDict, errorsDict)
        if int(valuesDict['pollingFrequency']) == 0:
            self.errorLog("Invalid entry for Polling Frequency - must be greater than 0")
            errorsDict = indigo.Dict()
            errorsDict['pollingFrequency'] = "Invalid entry for Polling Frequency - must be a whole number greater than 0"
            return (False, valuesDict, errorsDict)
        if int(valuesDict['requeststimeout']) == 0:
            self.errorLog("Invalid entry for Requests Timeout - must be greater than 0")
            errorsDict = indigo.Dict()
            errorsDict['requeststimeout'] = "Invalid entry for Requests Timeout - must be greater than 0"
            return (False, valuesDict, errorsDict)
        
        return (True, valuesDict)

   ########################################
    # UI Validate, Device Config
    ########################################
    def validateDeviceConfigUi(self, valuesDict, typeId, device):
        
        valuesDict['address'] = self.pluginPrefs["Postcode"]
        self.debugLog(valuesDict)
        return (True, valuesDict)

    

    ########################################
    # Menu Methods
    ########################################
    def toggleDebugging(self):
        if self.debug:
            indigo.server.log("Turning off debug logging")
            self.pluginPrefs["showDebugInfo"] = False
        else:
            indigo.server.log("Turning on debug logging")
            self.pluginPrefs["showDebugInfo"] = True
        self.debug = not self.debug
        
   