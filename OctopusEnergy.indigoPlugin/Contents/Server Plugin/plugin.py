#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2020 neilk
#
# Based on the sample dimmer plugin

################################################################################
# Imports
################################################################################
import indigo
import requests
import json
import time
import datetime
import csv
import os

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
        try:
        	pollingFreq = int(self.pluginPrefs['pollingFrequency'])
        except:
        	pollingFreq = 30

        try:
            while True:
                # we will check if we have crossed into a new 30 minute period every 30s (so worst case the update could be 30s late)
                # this is currently configurable (it may be lower as a default the check can be quick without hitting the API so that the rate change happens close to minute 00 and minute 30)
                # At present the polling frequency will determine the max number of seconds in a given period the tariff could be out of date
                self.sleep(1 * pollingFreq )
                for deviceId in self.deviceList:
                    # call the update method with the device instance
                    self.update(indigo.devices[deviceId])
        except self.StopThread:
            pass

    ########################################
    def update(self,device):

    	# Renamed UTC_Today to API_Today in devices.xml as it is now always the current day and will show the date the API data was refreshed, this will ensure existing devices are refreshed
    	device.stateListOrDisplayStateIdChanged()
        # The Tariff code is built from the Grid Supply Point (gsp) and the product code.  For the purposes of the plugin this is hardcoded to the agile offering
        # No need to vary this for the current version, but I will review in the future as it may be other tariffs than Agile may be of interest (even if they do not change every 30 mins)
        TARIFF_CODE="E-1R-"+PRODUCT_CODE+"-"+device.pluginProps['device_gsp']
        GET_STANDING_CHARGES = BASE_URL + "/products/" + PRODUCT_CODE + "/electricity-tariffs/" + TARIFF_CODE + "/standing-charges/"
        # Due to the way they API publishes the daily rates, I will force a refresh at 18:00 utc, as not all of the rates would have been available at midnight)

        ########################################################################
        # Reset Flags used to test the need to make half hour, daily and evening updates
        ########################################################################


        # Calculate 'now' using UTC as this will collect the correct tariff regardless of Daylight Savings, as the periods are reported in UTC (Z).  This will be the same baseline as the consumption data
        now = datetime.datetime.utcnow()
        # But calculate the applicable day using local time and the API will automatically adjust if it is BST and will ensure max, min and average align to the local time
        local_day = datetime.datetime.now().date()
        update_rate = False
        update_daily_rate = False

        ########################################################################
        # Check if the device state for the current tariff matches the "current period", if so no updates required
        ########################################################################


        # Rates are published from minute 00 to 30 and 30 to 00, work out which period we are in (0-29 mins first half, 30-59 second half)
        # We will use this to match to the results for the current period for the response
        if int(now.strftime("%M")) > 29:
            current_tariff_valid_period = (now.strftime("%Y-%m-%dT%H:30:00Z"))
        else:
            current_tariff_valid_period = (now.strftime("%Y-%m-%dT%H:00:00Z"))
        # Compare the current_tariff_valid_period with the one stored on the device to see if we need to update (we have crossed a half hour boundary)
        # If they match we can skip all of the updates and return, otherwise we update the period (and potentially the daily figures)
        if current_tariff_valid_period == device.states["Current_From_Period"]:
            self.debugLog("No need to update Current "+current_tariff_valid_period+" Stored "+device.states["Current_From_Period"])
        else:
            self.debugLog("Need to Update Current "+current_tariff_valid_period+" Stored "+device.states["Current_From_Period"])
            update_rate = True

        ########################################################################
        # If "update_rate is true" this will be the first run after either minute 00 or minute 30
        # We will then check if the API data needs to be refreshed, or other daily actions are Required
        # Such as the day changing when daily max, min and average need to be calculated
        # Or at 17:00 UTC when all of the rates for the current 24hour period will be available
        # Will now check if the daily updates are needed by comparing to the last day stored in the device state "API_Today"
        ########################################################################

        if str(local_day) != device.states["API_Today"] or current_tariff_valid_period == str(local_day)+"T17:00:00Z":
            indigo.server.log("Refreshing Rate Information from the Octopus API for Device "+ device.name)
            update_daily_rate = True
        else:
            self.debugLog("No Need to update daily - same utc day as last update "+device.name)
            update_daily_rate = False

        ########################################################################
        # Save yesterdays rates date into plugin props (the saved JSON of the daily rates)
        # This will be used in the future when the consumption device is available
        ########################################################################


        # Create update dictionary that will be used to minimise Indigo Server calls, will all be applied at the end of update in a single update states on server call
        device_states = []



        if update_daily_rate:

            ########################################################################
            # Save yesterdays rates date into plugin props (the saved JSON of the daily rates)
            # This will be used in the future when the consumption device is available
            ########################################################################

            # This should only happen once a day, not at 17:00Z so first do the copy to preserve yesterdays Rates only if the day has changed

            if str(local_day) != device.states["API_Today"]:
                device.pluginProps['yesterday_rates'] = device.pluginProps.get('today_rates',"")

            # Now make the call to the Octopus api to collect the 46 (at midnight) or 48 (in the 17:00 UTC call) rates for the day

            PERIOD="period_from="+str(local_day)+"T00:00&period_to="+str(local_day)+"T23:59"
            self.debugLog(PERIOD)
            GET_LOCAL_TARIFFS = BASE_URL+"/products/"+PRODUCT_CODE+"/electricity-tariffs/"+TARIFF_CODE+"/standard-unit-rates/?"+PERIOD
            try:
                response = requests.get(GET_LOCAL_TARIFFS, timeout=1)
                response.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.errorLog("Http Error "+ str(err))
                self.setErrorStateOnServer("No Update")
                return()
            except Exception as err:
                self.errorLog("Other error "+str(err))
                self.setErrorStateOnServer("No Update")
                return()
            if response.status_code ==200:
                results_json = response.json()
                #self.debugLog(results_json)
                half_hourly_rates = results_json['results']
                #self.debugLog(half_hourly_rates)
            else:
                self.debugLog("Error in getting current tariffs")

            ########################################################################
            # Iterate through the rate retured and calculate the
            # This will be used in the future when the consumption device is available
            ########################################################################

            sum_rates = 0
            max_rate = 0
            stored_rates=indigo.Dict()
            # This is the current rate cap for Agile Octopus, min value should always be lower than this, from the plugin config
            min_rate = str(self.pluginPrefs['Capped_Rate'])
            for rates in half_hourly_rates:
                sum_rates = sum_rates + rates["value_inc_vat"]
                if rates["value_inc_vat"] >= max_rate:
                    max_rate = rates["value_inc_vat"]
                if rates["value_inc_vat"] <= min_rate:
                    min_rate = rates["value_inc_vat"]
            average_rate = sum_rates / results_json['count']

            # Store the JSON response to the device so that the API doesn't need to be called every 30 mins
            updatedProps=device.pluginProps
            updatedProps['today_rates'] = json.dumps(half_hourly_rates)
            device.replacePluginPropsOnServer(updatedProps)
            self.debugLog(device.pluginProps)

            ########################################################################
            # Update the standing charge
            # Unlikely to change too often but the overhead is small so daily updates not excessive
            ########################################################################

            try:
                response = requests.get(GET_STANDING_CHARGES, timeout=1)
                response.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self.errorLog("Http Error "+ str(err))
            except Exception as err:
                self.errorLog("Other error"+err)
            if response.status_code ==200:
                standing_charge_json = response.json()
                standing_charge_inc_vat = float(standing_charge_json["results"][0]["value_inc_vat"])
                self.debugLog("Standard Charge "+str(standing_charge_inc_vat))
            else:
                self.errorLog("Error getting Standard Charges")

            # Append the updates to the updated states dict

            device_states.append({ 'key': 'Daily_Standing_Charge', 'value' : standing_charge_inc_vat , 'uiValue' :str(standing_charge_inc_vat)+"p" })
            device_states.append({ 'key': 'Daily_Average_Rate', 'value' : average_rate , 'decimalPlaces' : 4 })
            device_states.append({ 'key': 'Daily_Max_Rate', 'value' : max_rate , 'decimalPlaces' : 4 })
            device_states.append({ 'key': 'Daily_Min_Rate', 'value' : min_rate , 'decimalPlaces' : 4 })
            device_states.append({ 'key': 'API_Today', 'value' : str(local_day)})
            device.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)

        ########################################################################
        # Now parse the stored json in the device to check for the applicable rate
        # in this 30 minute period if an update is needed
        ########################################################################

        if update_rate:
            for rates in json.loads(device.pluginProps['today_rates']):
                if rates['valid_from'] == current_tariff_valid_period:
                    indigo.server.log("Current Rate inc vat is "+str(rates["value_inc_vat"]))
                    current_tariff = float(rates["value_inc_vat"])

            # Write the CSV file out at 18:00 UTC and if the checkbox is ticked in the device config
            # File name in the form 2020-04-28-devicename-Rates.csv in the folder from the plugin config
            # Now defaults to the plugin prefs folder if an empty path is specified
            if device.pluginProps['Log_Rates'] and current_tariff_valid_period == str(local_day)+"T17:00:00Z":
            	if self.pluginPrefs['LogFilePath'] == "":
            		self.errorLog("No directory path specified in the Plugin Configuration to save the CSV File")
            		DefaultCSVPath = "{}/Preferences/Plugins/{}".format(indigo.server.getInstallFolderPath(), self.pluginId)
            		self.errorLog("Defaulting to "+DefaultCSVPath)

            		self.pluginPrefs['LogFilePath']= DefaultCSVPath
            		if not os.path.isdir(self.pluginPrefs['LogFilePath']):
            			os.mkdir(self.pluginPrefs['LogFilePath'])
            	filepath = self.pluginPrefs['LogFilePath']+"/"+str(local_day)+"-"+device.name+"-Rates.csv"
            	with open(filepath, 'w') as file:
            		writer = csv.writer(file)
            		writer.writerow(["Period", "Tariff"])
            		for rates in json.loads(device.pluginProps['today_rates']):
            			writer.writerow([rates['valid_from'],rates['value_inc_vat']])
            # Append the hourly updates to the update dictionary
            device_states.append({ 'key': 'Current_Electricity_Rate', 'value' : current_tariff , 'uiValue' :str(current_tariff)+"p", 'clearErrorState':True })
            device_states.append({ 'key': 'Current_From_Period', 'value' : current_tariff_valid_period })

            # Apply State Updates to Indigo Server
            device.updateStatesOnServer(device_states)

        else:
            self.debugLog("No Half Hourly Updates Required")
        return()





    ########################################
    # UI Validate, Plugin Preferences
    ########################################
    def validatePrefsConfigUi(self, valuesDict):
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
        try:
            timeoutint=float(valuesDict['Capped_Rate'])
        except:
            self.errorLog("Invalid entry for  Capped Rate - must be a number")
            errorsDict = indigo.Dict()
            errorsDict['Capped_Rate'] = "Invalid entry for Capped Rate - must be a number"
            return (False, valuesDict, errorsDict)
        if valuesDict['LogFilePath'] !="":
        	if not os.path.isdir(valuesDict['LogFilePath']):
        		errorsDict = indigo.Dict()
        		errorsDict['LogFilePath'] = "Directory specified does not exist"
        		self.errorLog(valuesDict['LogFilePath']+ " directory does not exist")
        		return (False, valuesDict, errorsDict)
        	if not os.access(valuesDict['LogFilePath'], os.W_OK):
        		errorsDict = indigo.Dict()
        		errorsDict['LogFilePath'] = "Directory specified is not writable"
        		self.errorLog(valuesDict['LogFilePath']+ " directory is not writable")
        		return (False, valuesDict, errorsDict)
        return (True, valuesDict)

   ########################################
    # UI Validate, Device Config
    ########################################
    def validateDeviceConfigUi(self, valuesDict, typeId, device):
	if not(valuesDict['Device_Postcode']):
            self.errorLog("Postcode Cannot Be Empty")
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "Postcode Cannot Be Empty"
            return (False, valuesDict, errorsDict)
        try:
            response = requests.get(BASE_URL+GET_GSP+valuesDict['Device_Postcode'], timeout=1)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:

            self.debugLog("Http Error "+ str(err))
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "Error validating with Octopus"
            return (False, valuesDict, errorsDict)
        except Exception as err:
            self.debugLog("Other error"+str(err))
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "Error validating with Octopus"
            return (False, valuesDict, errorsDict)
        else:
            self.debugLog("Connected to Octopus Servers")
        if response.status_code ==200:
            gsp_json =  response.json()
            if gsp_json['count']==0:
                self.debugLog("GSP Not returned")
                errorsDict = indigo.Dict()
                errorsDict['Device_Postcode'] = "GSP Not returned - Check Postcode"
                return (False, valuesDict, errorsDict)
            else:
                gsp= gsp_json['results'][0]['group_id'][1]
                self.debugLog("GSP is "+gsp)
                valuesDict['device_gsp'] = gsp
        else:
            gsp = "Unknown API Error"
            self.debugLog(response)
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "Unknown Octopus API Error"
            return (False, valuesDict, errorsDict)
        valuesDict['address'] = valuesDict['Device_Postcode']
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
