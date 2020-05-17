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
        # and the additional yesterdays states and any future updates will be applied

    	device.stateListOrDisplayStateIdChanged()


        # The Tariff code is built from the Grid Supply Point (gsp) and the product code.  For the purposes of the plugin this is hardcoded to the agile offering
        # No need to vary this for the current version, but I will review in the future as it may be other tariffs than Agile may be of interest (even if they do not change every 30 mins)
        TARIFF_CODE="E-1R-"+PRODUCT_CODE+"-"+device.pluginProps['device_gsp']
        GET_STANDING_CHARGES = BASE_URL + "/products/" + PRODUCT_CODE + "/electricity-tariffs/" + TARIFF_CODE + "/standing-charges/"
        # Due to the way they API publishes the daily rates, I will force a refresh at 17:00 utc, as not all of the rates would have been available at midnight the previous day)

        ########################################################################
        # Reset Flags used to test the need to make half hour, daily and evening updates
        ########################################################################


        # Calculate 'now' using UTC as this will collect the correct tariff regardless of Daylight Savings, as the periods are reported in UTC (Z).  This will be the same baseline as the consumption data
        now = datetime.datetime.utcnow()
        # But calculate the applicable day using local time and the API will automatically adjust if it is BST and will ensure max, min and average align to the local time
        local_day = datetime.datetime.now().date()
        # Also calculate yesterday as this will be used to get yesterdays rates
        local_yesterday = datetime.datetime.now().date()  - datetime.timedelta(days=1)
        # Flag used to see if the rate needs to be updated
        update_rate = False
        # Flag used to see if the daily rate needs to be updates
        update_daily_rate = False
        # Flag used to determine if this is the 17:00Z update cycle
        update_afternoon_refresh = False
        #Flag used to mark API errors for the todays rate call
        api_error = False
        #Flag used to mark API error getting yesterdays rates
        api_error_yest = False


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
            self.debugLog("No need to update Current "+current_tariff_valid_period+" Stored "+device.states["Current_From_Period"]+" for "+device.name)
        else:
            self.debugLog("Need to Update Current "+current_tariff_valid_period+" Stored "+device.states["Current_From_Period"]+" for "+device.name)
            update_rate = True

        if update_rate:
            ########################################################################
            # If "update_rate is true" this will be the first run after either minute 00 or minute 30
            # We will then check if the API data needs to be refreshed, or other daily actions are Required
            # Such as the day changing when daily max, min and average need to be calculated
            # Or at 17:00 UTC when all of the rates for the current 24hour period will be available
            # Will now check if the daily updates are needed by comparing to the last day stored in the device state "API_Today"
            ########################################################################

            if str(local_day) != device.states["API_Today"]:
                update_daily_rate = True
            else:
                self.debugLog("No Need to update daily - same day as last update "+device.name)
                update_daily_rate = False

            ########################################################################
            # Now check if it is 17:00Z and if the afternoon update has been completed
            # If it is 17:00Z and the update has not been done then set to True
            ########################################################################

            if current_tariff_valid_period == str(local_day)+"T17:00:00Z" and device.states['API_Afternoon_Refresh'] == False:
                indigo.server.log("Applying the Afternoon Daily Rate Update from the Octopus API for Device "+ device.name)
                update_afternoon_refresh = True
            else:
                self.debugLog("No Need for the Afternoon refresh - it is not 17:00Z or it has been done  for "+device.name)
                update_afternoon_refresh = False

            ########################################################################
            # Now start doing the various updates based on the conditions
            ########################################################################

            # Create update list that will be used to minimise Indigo Server calls, will all be applied at the end of update in a single update states on server call
            device_states = []

            ########################################################################
            # The rates should only need to be updated against the API at 00:00 "OR" at 17:00Z
            ########################################################################

            if (update_daily_rate or update_afternoon_refresh):

                ########################################################################
                # Now Make the API calls
                ########################################################################


                indigo.server.log("Refreshing Daily Rate Information from the Octopus API for Device "+ device.name)

                PERIOD="period_from="+str(local_day)+"T00:00&period_to="+str(local_day)+"T23:59"
                self.debugLog(PERIOD)
                GET_LOCAL_TARIFFS = BASE_URL+"/products/"+PRODUCT_CODE+"/electricity-tariffs/"+TARIFF_CODE+"/standard-unit-rates/?"+PERIOD
                try:
                    response = requests.get(GET_LOCAL_TARIFFS, timeout=float(self.pluginPrefs['requeststimeout']))
                    response.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    self.errorLog("Octopus API refresh failure, Http Error "+ str(err))
                    device_states.append({ 'key': 'API_Today', 'value' : "API Refresh Failed"})
                    device.setErrorStateOnServer("No Update")
                    api_error = True
                except Exception as err:
                    self.errorLog("Octopus API refresh failure, Other error "+str(err))
                    device_states.append({ 'key': 'API_Today', 'value' : "API Refresh Failed"})
                    device.setErrorStateOnServer("No Update")
                    api_error = True
                # If API request succeeded, then save the response, and update the "API_Today" device state
                try:
                    if response.status_code ==200:
                        results_json = response.json()
                        #self.debugLog(results_json)
                        half_hourly_rates = results_json['results']
                        # Update the device state to show the API update has run sucessfully
                        device_states.append({ 'key': 'API_Today', 'value' : str(local_day)})
                        self.debugLog("Got the rates OK")
                        if current_tariff_valid_period == str(local_day)+"T17:00:00Z":
                            self.debugLog("Setting Afternoon refresh done to device state")
                            device_states.append({ 'key': 'API_Afternoon_Refresh', 'value' : True })
                # Catch all other possible failures
                except:
                    self.errorLog("Octopus API Refresh, Error in getting current tariffs")
                    device_states.append({ 'key': 'API_Today', 'value' : "API Refresh Failed"})
                    device.setErrorStateOnServer("No Update")

                ########################################################################
                # Iterate through the rate retured and calculate the
                # Max, min and average
                ########################################################################

                if not api_error:
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

                # Update the states to be applied to the server for the todays rates if the API call succeeded

                    device_states.append({ 'key': 'Daily_Average_Rate', 'value' : average_rate , 'decimalPlaces' : 4 })
                    device_states.append({ 'key': 'Daily_Max_Rate', 'value' : max_rate , 'decimalPlaces' : 4 })
                    device_states.append({ 'key': 'Daily_Min_Rate', 'value' : min_rate , 'decimalPlaces' : 4 })
                    device_states.append({ 'key': 'API_Today', 'value' : str(local_day)})

                ########################################################################
                # Store the JSON response to the device so that the API doesn't need to be called every 30 mins
                ########################################################################
                updatedProps=device.pluginProps
                if not api_error:
                    updatedProps['today_rates'] = json.dumps(half_hourly_rates)

                ########################################################################
                # Get Yesterdays Rates from the API (rather than copying yesterdays)
                # This is more robust and will provide yesterdays data on the first device update
                # Also it does not matter if this is run at a different time as it is now
                # Does not over-write but recalculates correctly
                ########################################################################


                YESTERDAY_PERIOD="period_from="+str(local_yesterday)+"T00:00&period_to="+str(local_yesterday)+"T23:59"
                GET_YESTERDAY_TARIFFS = BASE_URL+"/products/"+PRODUCT_CODE+"/electricity-tariffs/"+TARIFF_CODE+"/standard-unit-rates/?"+YESTERDAY_PERIOD

                try:
                    yesterday_response = requests.get(GET_YESTERDAY_TARIFFS, timeout=float(self.pluginPrefs['requeststimeout']))
                    yesterday_response.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    self.errorLog("Octopus API refresh failure (Yesterday refresh), Http Error "+ str(err))
                    api_error_yest = True
                except Exception as err:
                    self.errorLog("Octopus API refresh failure (Yesterday refresh), Other error "+str(err))
                    api_error_yest = True
                # If API request succeeded, then save the response, and update the "API_Today" device state
                try:
                    if yesterday_response.status_code ==200:
                        yesterday_results_json = yesterday_response.json()
                        #self.debugLog(results_json)
                        yesterday_half_hourly_rates = yesterday_results_json['results']
                        # If this is the 17:00Z run then update the device state to show it has been completed
                        if update_afternoon_refresh:
                            self.debugLog("Setting Afternoon refresh done to device state")
                            device_states.append({ 'key': 'API_Afternoon_Refresh', 'value' : True })
                # Catch all other possible failures
                except:
                    self.errorLog("Octopus API Refresh, Error in getting yesterday tariffs")
                

                ########################################################################
                # Iterate through the rate retured and calculate the
                # Max, min and average for yesterday
                ########################################################################

                if not api_error_yest:
                    sum_rates_yest = 0
                    max_rate_yest = 0
                    stored_rates_yest = indigo.Dict()
                    # This is the current rate cap for Agile Octopus, min value should always be lower than this, from the plugin config
                    min_rate_yest = str(self.pluginPrefs['Capped_Rate'])
                    for rates in yesterday_half_hourly_rates:
                        sum_rates_yest = sum_rates_yest + rates["value_inc_vat"]
                        if rates["value_inc_vat"] >= max_rate_yest:
                            max_rate_yest = rates["value_inc_vat"]
                        if rates["value_inc_vat"] <= min_rate_yest:
                            min_rate_yest = rates["value_inc_vat"]
                    average_rate_yest = sum_rates_yest / yesterday_results_json['count']

                ########################################################################
                # Store the JSON response to the device so that the API doesn't need to be called every 30 mins
                ########################################################################

                if not api_error_yest:
                    updatedProps['yesterday_rates'] = json.dumps(yesterday_half_hourly_rates)
                    
                if not api_error and not api_error_yest:
                    device.replacePluginPropsOnServer(updatedProps)
                    device_states.append({ 'key': 'Yesterday_Standing_Charge', 'value' : device.states['Daily_Standing_Charge'] , 'uiValue' :str(device.states['Daily_Standing_Charge'])+"p" })
                    device_states.append({ 'key': 'Yesterday_Average_Rate', 'value' : average_rate_yest , 'decimalPlaces' : 4 })
                    device_states.append({ 'key': 'Yesterday_Max_Rate', 'value' : max_rate_yest , 'decimalPlaces' : 4 })
                    device_states.append({ 'key': 'Yesterday_Min_Rate', 'value' : min_rate_yest , 'decimalPlaces' : 4 })
                if not update_afternoon_refresh:
                    device_states.append({ 'key': 'API_Afternoon_Refresh', 'value' : False })
                    self.debugLog("Resetting Afternoon Refresh to False")
                self.debugLog("Updating yesterday rates")

                ########################################################################
                # Update the standing charge
                # Unlikely to change too often but the overhead is small so twice daily updates not excessive
                ########################################################################

                try:
                    response = requests.get(GET_STANDING_CHARGES, timeout=float(self.pluginPrefs['requeststimeout']))
                    response.raise_for_status()
                except requests.exceptions.HTTPError as err:
                    self.errorLog("Octopus API - Standing Charge Http Error "+ str(err))
                except Exception as err:
                    self.errorLog("Octopus API - Standing Charge Other error"+err)
                if response.status_code ==200:
                    standing_charge_json = response.json()
                    standing_charge_inc_vat = float(standing_charge_json["results"][0]["value_inc_vat"])
                    device_states.append({ 'key': 'Daily_Standing_Charge', 'value' : standing_charge_inc_vat , 'uiValue' :str(standing_charge_inc_vat)+"p" })
                    self.debugLog("Standing Charge "+str(standing_charge_inc_vat))
                else:
                    self.errorLog("Octopus API - Standing Charge Error getting Standing Charges")

                # Append the updates to the updated states dict and change the state image

				#Moved into the if response
                #device_states.append({ 'key': 'Daily_Standing_Charge', 'value' : standing_charge_inc_vat , 'uiValue' :str(standing_charge_inc_vat)+"p" })
                device.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)

                # If this is the first update the yesterday standing charge will be set to zero, this applies todays rate to yesterday
                # as this is better than it appearing as zero.  risk that if the rate changed the day before you created the device the update will be 1 day late
                # but this unlikely risk is better than it appearing to be zero

                if device.states["Yesterday_Standing_Charge"]== 0:
                	device_states.append({ 'key': 'Yesterday_Standing_Charge', 'value' : standing_charge_inc_vat , 'uiValue' :str(standing_charge_inc_vat)+"p" })

                ########################################################################
                # This ends the indented section that only runs
                # if it is 00:00 or 17:00Z
                ########################################################################
            else:
            	self.debugLog("No Updates required for device through daily_update or afternoon refresh for "+device.name)

            	########################################################################
                # Write the CSV file out at 18:00 UTC and if the checkbox is ticked in the device config
                # File name in the form 2020-04-28-devicename-Rates.csv in the folder from the plugin config
                # Now defaults to the plugin prefs folder if an empty path is specified
                ########################################################################

                if device.pluginProps['Log_Rates'] and current_tariff_valid_period == str(local_day)+"T18:00:00Z":
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

            ########################################################################
            # Now parse the stored json in the device to check for the applicable rate
            # in this 30 minute period if an update is needed
            ########################################################################

            for rates in json.loads(device.pluginProps['today_rates']):
                # Find the record with the matching current tariff period in the saved JSON
                if rates['valid_from'] == current_tariff_valid_period:
                    indigo.server.log("Current Rate inc vat is "+str(rates["value_inc_vat"]))
                    current_tariff = float(rates["value_inc_vat"])

            ########################################################################
            # Append the half hourly updates to the update dictionary but not if an API refresh failed (which will force future attempts to refresh)
            ########################################################################

            device_states.append({ 'key': 'Current_Electricity_Rate', 'value' : current_tariff , 'uiValue' :str(current_tariff)+"p", 'clearErrorState':True })
            device_states.append({ 'key': 'Current_From_Period', 'value' : current_tariff_valid_period })

            ########################################################################
            # Apply State Updates to Indigo Server
            ########################################################################
            device.updateStatesOnServer(device_states)
            
            # Update the plugin props with the stored json for today and yeserdays rates

            
        else:
            self.debugLog("No Updates required for device through update_rate  for "+device.name)
		########################################################################
        # Nothing else needs to be done for this update, return to runConcurrentThread
        ########################################################################

        self.debugLog("Update cycle complete for "+ device.name )
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
            response = requests.get(BASE_URL+GET_GSP+valuesDict['Device_Postcode'], timeout=float(self.pluginPrefs['requeststimeout']))
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:

            self.debugLog("Http Error "+ str(err))
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "API Error validating with Octopus"
            return (False, valuesDict, errorsDict)
        except Exception as err:
            self.debugLog("Other error"+str(err))
            errorsDict = indigo.Dict()
            errorsDict['Device_Postcode'] = "API Error validating with Octopus"
            return (False, valuesDict, errorsDict)
        else:
            self.debugLog("API successfully Connected to Octopus Servers")
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

    def logDumpRawData(self):
    	for deviceId in self.deviceList:
    		self.debugLog(indigo.devices[deviceId].pluginProps)

    def logDumpRates(self):
    	for deviceId in self.deviceList:
    		indigo.server.log(indigo.devices[deviceId].name+" Today")
    		indigo.server.log("Period , Tariff")
    		for rates in json.loads(indigo.devices[deviceId].pluginProps['today_rates']):
    			indigo.server.log(rates['valid_from']+" , "+str(rates['value_inc_vat']))
    		indigo.server.log("Yesterday")
    		indigo.server.log("Period , Tariff")
    		for rates in json.loads(indigo.devices[deviceId].pluginProps['yesterday_rates']):
    			indigo.server.log(rates['valid_from']+" , "+str(rates['value_inc_vat']))
    			
    # Force API refresh on all devices at next cycle
    
    def forceAPIrefresh(self):
    		for deviceId in self.deviceList:
    			indigo.server.log(indigo.devices[deviceId].name+" Set for refresh on next cycle")
    			indigo.devices[deviceId].updateStateOnServer(key='API_Today', value='API Refresh Requested')
    			indigo.devices[deviceId].updateStateOnServer(key='Current_From_Period', value='API Refresh Requested')

    ########################################
    # Action Methods
    ########################################

    # Write Todays rates to file
    def todayToFile(self,pluginAction, device):
    	local_day = datetime.datetime.now().date()
    	if self.pluginPrefs['LogFilePath'] == "":
    		self.errorLog("No directory path specified in the Plugin Configuration to save the CSV File")
    		DefaultCSVPath = "{}/Preferences/Plugins/{}".format(indigo.server.getInstallFolderPath(), self.pluginId)
    		self.errorLog("Defaulting to "+DefaultCSVPath)
    		self.pluginPrefs['LogFilePath']= DefaultCSVPath
    	if not os.path.isdir(self.pluginPrefs['LogFilePath']):
    		os.mkdir(self.pluginPrefs['LogFilePath'])
    	filepath = self.pluginPrefs['LogFilePath']+"/"+str(local_day)+"-"+device.name+"-Action-Today-Rates.csv"
    	with open(filepath, 'w') as file:
    		writer = csv.writer(file)
    		writer.writerow(["Period", "Tariff"])
    		for rates in json.loads(device.pluginProps['today_rates']):
    			writer.writerow([rates['valid_from'],rates['value_inc_vat']])
    	indigo.server.log("Created CSV file "+filepath+" for device "+ device.name)
    	return()

    # Write Yesterdays rates to file
    def yesterdayToFile(self,pluginAction, device):
    	local_day = datetime.datetime.now().date()
    	if self.pluginPrefs['LogFilePath'] == "":
    		self.errorLog("No directory path specified in the Plugin Configuration to save the CSV File")
    		DefaultCSVPath = "{}/Preferences/Plugins/{}".format(indigo.server.getInstallFolderPath(), self.pluginId)
    		self.errorLog("Defaulting to "+DefaultCSVPath)
    		self.pluginPrefs['LogFilePath']= DefaultCSVPath
    	if not os.path.isdir(self.pluginPrefs['LogFilePath']):
    		os.mkdir(self.pluginPrefs['LogFilePath'])
    	filepath = self.pluginPrefs['LogFilePath']+"/"+str(local_day)+"-"+device.name+"-Action-Yesterday-Rates.csv"
    	with open(filepath, 'w') as file:
    		writer = csv.writer(file)
    		writer.writerow(["Period", "Tariff"])
    		for rates in json.loads(device.pluginProps['yesterday_rates']):
    			writer.writerow([rates['valid_from'],rates['value_inc_vat']])
    	indigo.server.log("Created CSV file "+filepath+" for device "+ device.name)
    	return()
    	


	#Was getting strange behaviour as when I wrote the json to the plugin props the device would restart causing a failed update
	#Found this was intended unless this method was defined.  Now will only restart if the address (postcode) changes.

    def didDeviceCommPropertyChange(self, origDev, newDev):
            if origDev.pluginProps['address'] != newDev.pluginProps['address']:
                return True
            return False
