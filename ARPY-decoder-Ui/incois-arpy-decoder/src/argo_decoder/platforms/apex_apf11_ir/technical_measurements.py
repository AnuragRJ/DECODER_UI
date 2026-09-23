"""APF11 timestamped source occurrences; no phase or completion-code inference.

Framing/layout: vendor apf11dec 2.12.2.1 and recovered Coriolis binary reader.
Routing: Coriolis d4069390, create_technical_time_series_apx_apf11_ir.m.
No timestamp deduplication: CSV companions remain separately traceable inputs.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import csv, gzip, hashlib, re, struct

# lookup, emitted variable, units, route. Coulomb units conflict in authorities;
# retain the raw value but fail closed on publication of that channel.
CHANNELS = (
 ('PRESSURE_AirBladder_dbar','PRESSURE_AirBladder','dbar','TECH'),
 ('PRESSURE_AirBladder_COUNT','PRESSURE_AirBladder_COUNT','count','AUX'),
 ('VOLTAGE_Battery_volts','VOLTAGE_Battery','volts','TECH'),
 ('VOLTAGE_Battery_COUNT','VOLTAGE_Battery_COUNT','count','AUX'),
 ('HUMIDITY_InsideHull_percent','HUMIDITY_InsideHull_percent','percent','AUX'),
 ('VOLTAGE_WaterLeakInsideHullDetection_volts','VOLTAGE_WaterLeakInsideHullDetection_volts','volt','AUX'),
 ('PRESSURE_InternalVacuum_dbar','PRESSURE_InternalVacuum','dbar','TECH'),
 ('PRESSURE_InternalVacuum_COUNT','PRESSURE_InternalVacuum_COUNT','count','AUX'),
 ('NUMBER_BatteryUsedCoulombCounts_mA_hour','NUMBER_BatteryUsedCoulombCounts_mA_hour',None,'BLOCKED'),
 ('CURRENT_Battery_mA','CURRENT_Battery_mA','milliampere','AUX'),
 ('CURRENT_Battery_COUNT','CURRENT_Battery_COUNT','count','AUX'),
)
WATCHDOG=('FIRMWARE_WATCHDOG_COUNT','FIRMWARE_WATCHDOG_COUNT','count','AUX')
CORE=struct.Struct('<IfHfHfffHffh')
WD=struct.Struct('<Ii')
EPOCH=datetime(1950,1,1,tzinfo=timezone.utc)

@dataclass(frozen=True)
class Occurrence:
    cycle: int
    kind: str
    timestamp: str
    values: tuple
    source: dict

    @property
    def identity(self):
        import json
        return hashlib.sha256(json.dumps(self.source,sort_keys=True).encode()).hexdigest()

    @property
    def juld(self):
        return (datetime.strptime(self.timestamp,'%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)-EPOCH).total_seconds()/86400

    def receipt(self):
        return {**asdict(self),'identity':self.identity}


def _companion_rows(path):
    """Entire vendor-rendered stream plus native frame identities, not time matching."""
    raw=path.read_bytes();data=gzip.decompress(raw);offset=0;rendered=[];native=[]
    while offset<len(data):
        size=data[offset];payload=data[offset+1:offset+1+size]
        if not size or len(payload)!=size:raise ValueError('Truncated companion frame')
        typ=payload[0];unix=struct.unpack('<I',payload[1:5])[0]
        ts=datetime.fromtimestamp(unix,timezone.utc).strftime('%Y%m%dT%H%M%S')
        vals=()
        if typ==0:row=['Message',ts,payload[5:].decode('utf-8')]
        elif typ==1:
            vals=CORE.unpack(payload[1:])[1:]
            row=['VITALS_CORE',ts]+[str(v) if i in (1,3,7,10) else f'{v:.3f}' for i,v in enumerate(vals)]
        elif typ==2:row=['RSSI',ts,str(struct.unpack('<IB',payload[1:])[1])]
        elif typ==3:
            vals=WD.unpack(payload[1:])[1:];row=['WD_CNT',ts,str(vals[0])]
        else:raise ValueError('Cannot prove complete companion equivalence for unknown record type')
        rendered.append(row);native.append((tuple(vals),{'file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'byte_offset':offset}))
        offset+=size+1
    return rendered,native


def read_technical_sources(paths, cycle):
    """Read explicit cycle-scoped paths. All supported occurrences, no time window.

    Return VITALS/WD occurrences and unassigned completion events. Other binary
    families are outside this reader's stated scope, not treated as measurements.
    """
    records=[];blocked=[]
    paths=sorted(map(Path,paths))
    for path in paths:
        raw=path.read_bytes();base={'file':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        data=gzip.decompress(raw) if path.suffix=='.gz' else raw
        if path.name.endswith(('.vitals_log.bin','.vitals_log.bin.gz')):
            offset=0
            while offset<len(data):
                size=data[offset];payload=data[offset+1:offset+1+size]
                if not size or len(payload)!=size:raise ValueError(f'Truncated frame: {path}:{offset}')
                typ=payload[0]
                if typ in (1,3):
                    vals=(CORE if typ==1 else WD).unpack(payload[1:])
                    stamp=datetime.fromtimestamp(vals[0],timezone.utc).strftime('%Y%m%dT%H%M%S')
                    records.append(Occurrence(cycle,'VITALS_CORE' if typ==1 else 'WD_CNT',stamp,tuple(vals[1:]),{**base,'byte_offset':offset,'record_id':typ,'unix_seconds':vals[0]}))
                offset+=size+1
        elif path.name.endswith('.vitals_log.csv'):
            csv_rows=list(csv.reader(data.decode('utf-8',errors='surrogateescape').splitlines()))
            companion=path.with_suffix('.bin.gz');native=None
            if companion in paths:
                rendered,native=_companion_rows(companion)
                if rendered!=csv_rows:raise ValueError('CSV is not an exact vendor-rendered companion; cannot substitute native precision')
            for line,row in enumerate(csv_rows,1):
                if row and row[0] in ('VITALS_CORE','WD_CNT'):
                    expected=11 if row[0]=='VITALS_CORE' else 1
                    if len(row)!=expected+2:raise ValueError(f'Wrong payload width: {path}:{line}')
                    vals=tuple(float(x) for x in row[2:]);source={**base,'line':line,'original_fields':row}
                    if native is not None:
                        vals,origin=native[line-1]
                        source['native_companion']=origin
                        source['precision_policy']='entire-stream companion proved; publish original native values, retain CSV text; no deduplication'
                    records.append(Occurrence(cycle,row[0],row[1],vals,source))
        elif path.name.endswith(('.system_log.txt','.system_log.txt.gz')):
            for line,text in enumerate(data.decode('utf-8',errors='surrogateescape').splitlines(),1):
                fields=text.split('|',3)
                if len(fields)!=4 or fields[2]!='BuoyEngine':continue
                match=re.search(r'(?:Buoyancy engine )?destination\s+(\d+)\s+reached',fields[3])
                if match:
                    blocked.append({'cycle':cycle,'timestamp':fields[0],'reported_count':int(match[1]),'source':{**base,'line':line,'original_line':text},'parameter':None,'MC':None,'pressure':None,'reason':'destination-completion publication identity not established'})
    # Validate clocks; never repair them or substitute ordering.
    for record in records:record.juld
    return records,blocked


def load_float_technical_records(raw_dir: Path, cycles: set[int] | None = None):
    """Load all cycle-scoped occurrences and blocked events across an entire float directory."""
    all_records = []
    all_blocked = []
    if not raw_dir.exists():
        return all_records, all_blocked
    files = list(raw_dir.glob("*.*"))
    by_cycle = {}
    for f in files:
        parts = f.name.split(".")
        if len(parts) > 2 and parts[1].isdigit():
            c = int(parts[1])
            if c > 0 and (cycles is None or c in cycles) and ("vitals_log" in f.name or "system_log" in f.name):
                by_cycle.setdefault(c, []).append(f)
    for c in sorted(by_cycle):
        recs, blk = read_technical_sources(by_cycle[c], c)
        all_records.extend(recs)
        all_blocked.extend(blk)
    return all_records, all_blocked

