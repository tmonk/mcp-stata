clear all
set more off
sysuse auto, clear
generate ratio = weight / length
label variable ratio "Weight-Length Ratio"
summarize price mpg weight length
tabulate foreign, gen(foreign_dummy)
regress price mpg weight foreign_dummy1
predict p_hat
gen res = price - p_hat
list make price p_hat res in 1/5
sort price
bysort foreign: summarize mpg
gen heavy = (weight > 3500)
label define hlbl 0 "Light" 1 "Heavy"
label values heavy hlbl
tabulate heavy foreign
correlate price mpg weight length
pwcorr price mpg weight length, sig
drop mpg
* We dropped mpg, now line 22 will fail
summarize price mpg weight
graph box price, over(foreign)
gen high_mpg = (mpg > 25)
regress price weight length
test weight = length
display "Finished analysis part 1"
save "final_data.dta", replace
log close
exit
