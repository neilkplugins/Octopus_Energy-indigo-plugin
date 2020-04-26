#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# Copyright (c) 2020 neilk
#
# Based on the sample dimmer plugin and various vehicle plugins for Indigo

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
# Initialise the daily update flag
daily_update = 0


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
        self.debugLog(device.pluginProps)

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
                # we will check if we have crossed into a new 30 minute period every 60s (so worst case the update could be 60s late)
                # this is currently configurable (it may be lower as a default the check can be quick without hitting the API so that the rate change happens close to minute 00 and minute 30)
                # At present the polling frequency will determine the max number of seconds in a given period the tariff could be out of date
                self.sleep(1 * pollingFreq )
                self.debugLog(self.deviceList)
                for deviceId in self.deviceList:
                    # call the update method with the device instance
                    self.update(indigo.devices[deviceId])
        except self.StopThread:
            pass

    ########################################
    def update(self,device):
        # The Tariff code is built from the Grid Supply Point (gsp) and the product code.  For the purposes of the plugin this is hardcoded to the agile offering
        # No need to vary this for the current version, but I will review in the future as it may be other tariffs than Agile may be of interest (even if they do not change every 30 mins)
        TARIFF_CODE="E-1R-"+PRODUCT_CODE+"-"+self.pluginPrefs['gsp']
        GET_STANDING_CHARGES = BASE_URL + "/products/" + PRODUCT_CODE + "/electricity-tariffs/" + TARIFF_CODE + "/standing-charges/"
        # utctoday is used as the baseline day for the min, max and average calculations.  Those updates will only run when the utc date changes (not GMT/BST)
        # Due to the way they API publishes the daily rates, I will force a refresh at 17:00 utc, as not all of the rates may have been available when the utc day changed)
        utctoday =datetime.datetime.utcnow().date()
        now = datetime.datetime.utcnow()
        update_rate = False
        update_daily_rate = False
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
        if update_rate:
            device_states = []
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

            # The standing charge, max and min values only need to be updated once a day
            if str(utctoday) != device.states["UTC_Today"]:
                self.debugLog("Updating daily values for max, min and standing charge")
                update_daily_rate = True
            else:
                self.debugLog("No Need to update daily - same utc day as last update")
                update_daily_rate = False
            sum_rates = 0
            max_rate = 0
            # This is the current rate cap for Agile Octopus, min value should always be lower than this, currently hard coded in the plugin as not published by the api
            min_rate = CAPPED_RATE
            for rates in half_hourly_rates:
                self.debugLog(rates)
                sum_rates = sum_rates + rates["value_inc_vat"]
                if rates["value_inc_vat"] >= max_rate:
                    max_rate = rates["value_inc_vat"]
                if rates["value_inc_vat"] <= min_rate:
                    min_rate = rates["value_inc_vat"]
                if rates['valid_from'] == current_tariff_valid_period:
                    self.debugLog("Current Rate inc vat is "+str(rates["value_inc_vat"]))
                    current_tariff = float(rates["value_inc_vat"])
            average_rate = sum_rates / results_json['count']
            # Only apply updates if it is a new utc day, or once a day at 18:00Z which will be when the next days rates will be published
            if update_daily_rate or current_tariff_valid_period == str(utctoday)+"T18:00Z":
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
                # Apply the daily upates if necessary
                device_states.append({ 'key': 'Daily_Standing_Charge', 'value' : standing_charge_inc_vat , 'uiValue' :str(standing_charge_inc_vat)+"p" })
                device_states.append({ 'key': 'Daily_Average_Rate', 'value' : average_rate , 'decimalPlaces' : 4 })
                device_states.append({ 'key': 'Daily_Max_Rate', 'value' : max_rate , 'decimalPlaces' : 4 })
                device_states.append({ 'key': 'Daily_Min_Rate', 'value' : min_rate , 'decimalPlaces' : 4 })

            # Apply the hourly updates
            device_states.append({ 'key': 'Current_Electricity_Rate', 'value' : current_tariff , 'uiValue' :str(current_tariff)+"p" })
            device_states.append({ 'key': 'Current_From_Period', 'value' : current_tariff_valid_period })
            device_state_append({ 'key': 'UTC_Today', 'value' : str(utctoday)})
            device.updateStateImageOnServer(indigo.kStateImageSel.EnergyMeterOn)
            # Apply State Updates to Indigo Server
            device.updateStatesOnServer(device_states)

        else:
            self.debugLog("No Hourly Updates Required")
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
