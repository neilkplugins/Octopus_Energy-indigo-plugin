# Octopus Energy Indigo Plugin
## A plugin for Indigo Domotics that connects to the UK Energy Provider Octopus Energy &amp; their Agile Tariff

Octopus Energy is a UK Energy Supplier that offers a number of Tariff's that appeal to Electric Vehicle (EV) owners, Tesla Powerwall (an Indigo plugin also is available for that) as well as those who may be able to shape their consumption by managing demand through home automation.  This plugin was initially built to assess the viability of the Agile Tariff for my personal use.   You will find more information at https://octopus.energy as well as their API (which this plugin uses) at https://developer.octopus.energy/docs/api/

The Agile Tariff is especially interesting as it offers a new electricity rate every 30 minutes, based on the then current wholesale rate for that 30 minute period.  This "Plunge Pricing" results in a much lower kWh price for electricity for times outside of the 16:00 to 19:00 peak.  You carry the risk if the price is higher during this period, but get the benefit when it falls lower.  A price cap applies of 35p per kWh, and for example the average today as I write this is 5.292p. the minimum 1.764p and the maximum 19.656p.  This compares with the fixed rate from my current supplier which is 15.4p. and again for today apart from 3 Hours the Agile rate would be below what I currently pay.

The really interesting thing is that this can also result in negative pricing, typically at times for example when it is windy  during a period of low demand (UK has a reasonable amount of wind turbine capacity).  At these times they will actually pay you to consume energy, these situations are relatively rare but it does mean you can charge you EV to store what will still be very cheap energy, even when the price is not negative.  I will be using this to trigger charging my EV, using another plugin that can start and stop charging (Indigo has plugin's for a number of EV's, including in my case an I-Pace).

The plugin does not require you to make a switch to Octopus, to use it you can simply enter your postcode as the prices vary by region in the UK.  The plugin can create a device that will show the current kWh price for you location (or indeed mutliple locations) , the daily standing charge, the maximum, minimum and average rates.  All these device states can be graphed if you use one of the graphing plugins, you can trigger based on those values or thresholds.  If you can measure your whole house demand (even manually using your smart meter in House display) you can project your savings.

The next major version (pre-release right now) will correct the behaviour of the Max, Min and Average rates such that they reflect the current day, rather than being based on UTC, which on reflection was lazy on my part. I also need to figure out the best approach to deal with the fact it is only possible to get a real update aftert 16:00 BST as only then are all 48 periods in the day published.

I am in the process of switching to Octopus Agile and when complete I will then incorporate the consumption data capabilities of the API.  My goal with this will be to track actual historical cost for each 30 minute period, this will only be possible for the previous 24 Hours as Octopus do not publish consumption data real time.  The plugin will optionally generate a daily CSV containing the rates for the current day, and a seperate action for yesterdays rates.  The current pre-release version optimises the API access such that only 2 calls a day are made.

Comments and feedback extremely welcome, via the Indigo Plugin Forum at 
I am also issue tracking in this repository

Documentation at https://github.com/neilkplugins/Octopus_Energy-indigo-plugin/wiki

I have started my switch and if you do so then please use my referall code https://share.octopus.energy/cute-peak-364 , and we could both get a £50 credit.  Any I get will be donated to the Children's Oncology Suites at the Royal Berkshire Hospital's Lion Ward once they hit my account.
