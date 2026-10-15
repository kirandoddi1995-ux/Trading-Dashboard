# Evidence and remaining programme — 15 October 2026

## Decisions

1. Morning commissioning uses already-green public1251530; no overnight source
   replaces installed capture or changes the index window. If the strict morning
   sequence cannot finish, retain partial evidence and commission a later session.
2. Preserve14Oct before any NEW state-root writer. A quiescent hashed copy is a
   preservation proof, not an encrypted independent replica, custody or restore.
3. Diagnose and classify operations without inventing a cause. A process block,
   notification launch, sync query or job's queue receipt is not delivery proof.
4. Implement a consistent-cut read-only exporter BEFORE retention and factory
   switching. Demonstrate failures offline before any owner native test or SQL
   commissioning. No new migration, SQLwriter, deletes or secrets this run.
5. Real-data research starts with a frozen prospective observational-index study
   and honest readiness reporting. Index snapshots cannot supply option/future
   executable labels, intraday margins, spread/depth or fill probabilities.

## Verified / reported / not verified

VERIFIED: publicclone HEAD1251530731cce5b75fad8601567b9320d07b710d. Public API
reports quality410, resilience348, dynamicCodeQL522 and release176–178 successful
for that SHA. This does NOT establish publishing/commissioning; release hold
unchanged. New source remains review-only, not part of today's installed capsule.

OWNER-REPORTED:14Oct two terminalverified polls, no automatic tasks enabled; all
six tasks disabled, legacy raw audit exported/disabled. Actual privatejournal,
XML/receipts, alertmarkers and time-service events were NOT inspected by agent.

NOT VERIFIED: originalcapsule compatibility, all hashes of14Oct originals,
actual journal/receipt evidence, actual notifications, WindowsTime rootcause,
hostrestart/sleep, originallegacy audit writes, archivecustody/restore/licence,
steady-state quota, everyfactoryguard, real models/labels/LLMbackend. No falseflags
are switched true by publicchecks or this document.

## Separately reviewed historical14Oct audit path

FIRST preserve and verify source files with all writer tasks disabled. Keep the
original capsule unchanged. Current public read-only audit may fail correctly
because stored source/environment pins precede1251530. That mismatch is evidence,
not an instruction to update config, use a flag, copy a new helper into old code,
monkeypatch a validator, downgrade main or run Producer.

This owner-only alternative uses the ORIGINAL interpreter/code validators and
the existing original `overnight_capture_audit.journal_bytes` SELECT-only path.
It retains pausedjournal/sidecar/lock/schema/hash/source/environment checks;
only two generation counts and hashes are printed. It writes neither reports
nor notifications nor captures. No fallback if dependencies/recipe fail. This
adapter has been source-reviewed; its existing SELECT-only primitive has public
synthetic coverage. The exact inline historical launcher and your original
capsule acceptance remain unverified; no real historical execution is claimed.

Normal owner PowerShell, after preservation; choose explicit original code and
interpreter; NOnewcapsulefiles installed into that folder:

```powershell
$historicalCode = 'C:\Users\banga\Desktop\kiran_forward_20261014'
$historicalPython = Join-Path $historicalCode '.venv\Scripts\python.exe'
Set-Location -LiteralPath $historicalCode
$historicalAudit = @'
import json, sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from forward_revision_evidence import private_read
    from overnight_capture_audit import journal_bytes, audit_bytes
    session = Path(sys.argv[1])
    if not session.is_absolute() or session.name != '2026-10-14':
        raise ValueError('wrong session')
    config = json.loads(private_read(session / 'config.json'))
    recipe = json.loads(private_read(session / 'state/versioned-v1/recipe.json'))
    if datetime.fromisoformat(config['session_open']).astimezone(ZoneInfo('Asia/Kolkata')).date() != date(2026,10,14):
        raise ValueError('wrong date')
    if datetime.now(ZoneInfo('Asia/Kolkata')) < datetime.fromisoformat('2026-10-14T15:40:00+05:30'):
        raise ValueError('postclose only')
    raw = journal_bytes(session / 'state/versioned-v1/journal.sqlite', config, recipe, source_root=Path.cwd())
    result = asdict(audit_bytes(raw, source_root=Path.cwd()))
    result.update(status='HISTORICAL_LOCAL_AUDIT_VERIFIED', writes=0, network_calls=0, credential_reads=0, original_runtime_compatibility_verified=True)
    print(json.dumps(result, sort_keys=True))
except Exception:
    print(json.dumps(dict(status='BLOCKED', code='HISTORICAL_READ_ONLY_REPLAY_REQUIRED', writes=0, network_calls=0, credential_reads=0, approval_authority=False)))
    sys.exit(2)
'@
& $historicalPython -B -c $historicalAudit (Join-Path $forwardPrivateState '2026-10-14')
if ($LASTEXITCODE -ne 0) { throw 'STOP: historical audit blocked; preserve, do not change pins or retry capture' }
```

Original Python executes inside original source root. -B suppresses bytecode
writes. SQLite mode=ro/query_only plus pausedsidecar refusal remains mandatory.
A validgeneration with recorded2/missing73 is a partialrehearsal, not a75slot
session or modeltrainingcohort. A blocked result is unresolved; inspect privately
without bypasses. This procedure never reads a token or creates a connection to
Upstox/Drive/Supabase. App boot/model/backend are not involved.

##14Oct marker and legacy audit

Source review: operationsv2 notifications use day, public cause(code/stage/category)
digest and bounded launch states.14Oct cannot suppress15Oct. Pendinglaunchunknown
is deliberately not retried; failedlaunch has a bounded retry budget. A marker
is not delivery proof. Do not delete/migrate the old marker; use a separate owner
interactive rehearsal and separately test actual task-session delivery.

Legacy exit2 alone cannot identify exception or exclude writes: original
forward_nifty_schedule.main catches failures and calls scheduler receipt writer.
No invented conclusion about which14Octfile it wrote. Before new sharedrootwrites,
owner privately inventories `scheduler-receipts` timestamps/hashes around15:40
and existing14Octconfig/state timestamps/hashes. Preserve old receipts. Do not
display fileIDs, prices, pathvalues or rawexceptions. Sessionpreservationhelper
does not claim coverage of top-levelschedulerreceipts or separateopsroot.

##Clock and host

Microsoft documents standalone/workgroup WindowsTime trigger behavior: Auto may
not be enough to explain/service every condition. This supports inspecting
triggers/eventrecords; it does NOT establish why thisPCstopped at12:48. No agent
servicechanges, automatic resync, triggerdeletion or clockgaterelaxation. Owner
resync once beforepreflight, then producer measures independently perpoll.
[Microsoft workgroup W32Time guidance](https://learn.microsoft.com/en-us/troubleshoot/windows-client/active-directory/w32time-not-start-on-workgroup).

Sleep/hibernation/restart/logon are hostdependencies. Continuous timegate failures
correctly lose evidence; they must become visible early, not be retried as new
marketobservations. Publicinspection cannot prove the owner's interactive alert
session; humanrehearsal and firstrealtrigger are pending. Off-PCmissedrun alerts
remain engineering/ownercommissioning, not local MessageBox equivalence.

##Calendar and timing

Reviewed annualcashcalendar says15/16/19regular,17/18weekend,20OctDussehraclosed,
21regular; NSE notice agrees. No fixedrecurringtask acrossdates. Source:
[CMTR71775 annual notice](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).
An annualcalendar does not eliminate a later emergency/amendment; owner verifies
currentmarketstatus and preopenfile date. Derivativeclosing15:40 is a SEPARATE
contract question. Keep indexrecorder09:15–15:30 and audit15:40unchanged. Expiry
calendar, lasttradingtime and margin/settlement need officialdatedinstrumentrules.

##Skipped research option snapshots: current evidence

Read-only publicAPI: latest run60(id38593126254) event schedule, head161ffe0,
created14Oct15:52:15UTC; capturejob skipped with ZEROsteps. Recent runs53–59
also schedule/skipped. Workflow's job condition admits schedule ONLY when
OPTION_CAPTURE_ENABLED=='true'. We did NOT inspect that variable/accountsettings.
Inference: jobgate was not satisfied; there is no capture/token/Driveerror in
those skipped jobs. Timestampdelay is a separate symptom; don't assign an exact
targetcron from created_at alone or fabricate a missing snapshot.

GitHub explicitly permits scheduledelays/drops; schedule is defaultbranch and
public60dayinactivitydisable applies. Review readonly runevent/head/jobcondition,
actualscheduledexpression and expectedISTslot; variable names only, no secrets.
No workflowenabled/dispatch/setting changed. Do not manuallycatchup an oldslot.
[GitHub schedule semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

##Storage next criticalpath, zero-cost

Singleexplicit READONLY REPEATABLEREAD snapshot for rows/count/nativeaggregate;
servercursor/keysetpages ordered and bounded, no HTTP inside SQL transaction.
Timeouts/budgets prevent longsnapshotvacuuminterference. Exact objectsetpublication
and readback prove byteidentities, NOT licences/replicaindependence/restore.
[Postgres17 repeatable-read](https://www.postgresql.org/docs/17/transaction-iso.html#XACT-REPEATABLE-READ).
[Supabase database size](https://supabase.com/docs/guides/platform/database-size)
distinguishes allocatorquota from reusable space; no freshclustermeasurement was
made tonight.394MB and0.75MB/scan are OWNERestimates, not fresh capacityproof.
Livefactoryswitch/retention remain blocked until exactsourcecut, independent
custody, realrestore, allwriteradmission and peakcapacity/nativeproofs exist.

Priority aftermorning: nativeexporter race/completeness → exactobjectpublication
→ independentencryptedreplica+restore → writer/coldreaderfactoryinventory and
guardwiring → universecontenthashshadow → sourceboundedretention → wholecycle
spaceproof. Ledger must retain authentic chain/hotheads/recovery dependencies;
dailyvolume maximum is not finalexchangevolume or historicalavailability.
No cutdeletion/pruning approved by offline evidence. Existing collectorrecurrence
and holdsettings unchanged; no more indiscriminate reliefreclaims proposed.

##Real-data study, ML and Evidence Assistant

Firstfrozenprospective study is index-only observational capture/versions/gaps,
not a profitableF&Ostrategy. Register protocolBEFORE cohort observations; no
retrodecisionsfromMondayquarantine, no rewriterevisedbar, no sealedhistorical
2025/2026inspection. Forward2026ownerjournal is a separateprospective scope,
not permission to unseal2026holdout. Rawavailable_at feeds PIT, not finalversion.

Require documentedprovider/NSEdata rights for intendedstorage/analysis/ML and
privatearchive: freeaccess does not imply unrestrictedreuse/licence. Verify
intendedusage with provider/NSE/professional before realtraining/publicdisplay.
[NSE data sharing policy](https://www.nseindia.com/static/market-data/nse-data-policy),
[Upstox historical candle documentation](https://upstox.com/developer/api-documentation/get-historical-candle-data/).

Use session-level expandingwalkforward, purging overlappingfeature/labelintervals,
fittransforms/calibration inside trainingonly, gap around testboundary and cluster
uncertainty. StandardTimeSeriesSplitgap is not generalintervalpurging and presumes
equallyspaced samples; missing captures violate that assumption. Existing
projectsessiongroup+purgecode is retained, not replacewith randomrowsplit.
[scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).

Fewpartialdays => INSUFFICIENT_EVIDENCE. Sessionminima are protocolplanningfloors,
not statisticalpowerproof. F&Olabels need realcontractquotes/bidask/depth/lot/expiry,
knowncosts+slippage and censored/missingoutcomes. No indexreturn relabelled tradable
optionPnL. Baseline/chance/trialcounts and frozenstudy hash belong to fullrecord.
LLM may explain verifiedreports and point to missingevidence, never inventnumbers
or create a training/decisionapproval. Backend staysdisabled, no keys/accounts.

##Item-by-item owner brief coverage

1.15Oct orderedblocks/timebranches supplied, realcapsule/tasks/notification ownerpending.
2.14Oct currentread-onlyaudit and separateoriginalvalidatorpath supplied, privateacceptancepending.
3.Markerdayisolation/sourcebehavior reviewed; actualnotification/legacywrites notverified.
4.Host/time/power/logon/eventreadonlychecks supplied; rootcause remainsunknown.
5.15–21Oct calendar checked against reviewedcode and officialnotice; windowsunchanged.
6.Boundedquiescent exactcopyhelper+hashmanifest beingtested; actualcopy ownerpending.
7.Public skippedjobs verified, gate inference distinguished from timing; settings untouched.
8.Consistent-cutdailyvolumeexport milestone offline; six-table/objectset/native/custody/
  factories/retention remain incomplete, no productionenforcementclaimed.
9.Prospectivecohortreadiness milestone offline; licensing/labels/realstudy/results/LLMblocked.
10.Newpackages carry pinnedbaseline/manifests/checkers; bothplatformchecks explicitly
  reported. Hostedexactcommit gates remain owneracceptance, not localinference.

Further engineering cannot be called complete because a runbook exists. The
checkpoint records exact tests/nativeacceptance gaps after terminalverification.
