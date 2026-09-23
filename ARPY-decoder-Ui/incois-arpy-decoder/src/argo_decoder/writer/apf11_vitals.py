"""Coriolis-compatible VITALS numeric controls with mandatory provenance receipts.

Current routing, not historical all-AUX names. NC_FLOAT follows the recovered dictionary and manual. Binary f32 values are
exact; CSV companions must be proved against the complete native stream.
Independent CSV values that cannot survive f32 exactly fail closed. No new MCs.
Unsupported channels/events remain in the receipt, never in a renamed variable.
"""
from pathlib import Path
import hashlib,json,gzip
import netCDF4
import numpy as np
from argo_decoder.nc.admt import DAC_INSTITUTION
from argo_decoder.platforms.apex_apf11_ir.technical_measurements import CHANNELS,WATCHDOG
from argo_decoder.writer.apf11_tech import build_tech_dataset,_write_str_char,_now
from argo_decoder.writer.apf11_policy import APF11_NC_FORMAT

class IncompleteTechnicalMapping(ValueError):
    def __init__(self,blocked):
        self.blocked=blocked
        super().__init__('Technical bundle incomplete: unmapped events or unit-unresolved channels; explicit partial controls required')


def _dataset(wmo,route,centre):
    """Structural shell for the route.

    TECH: the published STRING128 writer, extended with the numeric section.
    AUX: recovered Coriolis ``create_nc_tech_aux_file.m`` (format1.1),
    including its unconditional empty scalar section and per-parameter QC
    variables. The N_TECH_AUX_LABEL catalog is intentionally absent: its
    content is the decoder's parameter-label table for this float version,
    which is not present in the recovered authoritative sources.
    """
    if route=='TECH':return build_tech_dataset(wmo,[],data_centre=centre)
    ds=netCDF4.Dataset('aux-memory','w',diskless=True,format=APF11_NC_FORMAT)
    for n,s in [('STRING2',2),('STRING4',4),('STRING8',8),('STRING32',32),('STRING256',256),('STRING1024',1024),('DATE_TIME',14)]:ds.createDimension(n,s)
    ds.createDimension('N_TECH_PARAM',None)
    for n,d,v,attrs in [
      ('PLATFORM_NUMBER','STRING8',str(wmo),{'long_name':'Float unique identifier','conventions':'WMO float identifier : A9IIIII'}),
      ('DATA_TYPE','STRING32','Argo auxiliary technical data',{'long_name':'Data type','conventions':'Reference table AUX_1'}),
      ('FORMAT_VERSION','STRING4','1.1',{'long_name':'File format version'}),
      ('DATA_CENTRE','STRING2',centre,{'long_name':'Data centre in charge of float data processing','conventions':'Argo reference table 4'}),
      ('DATE_CREATION','DATE_TIME',_now(),{'long_name':'Date of file creation','conventions':'YYYYMMDDHHMISS'}),
      ('DATE_UPDATE','DATE_TIME',_now(),{'long_name':'Date of update of this file','conventions':'YYYYMMDDHHMISS'}),
    ]:
        _write_str_char(ds,n,d,v);ds[n].setncatts(attrs)
    _write_str_char(ds,'REFERENCE_DATE_TIME','DATE_TIME','19500101000000')
    ds['REFERENCE_DATE_TIME'].long_name='Date of reference for Julian days'
    ds['REFERENCE_DATE_TIME'].conventions='YYYYMMDDHHMISS'
    # Scalar auxiliary technical parameters: none for this VITALS routing.
    for n,dims in (('TECHNICAL_PARAMETER_NAME',('N_TECH_PARAM','STRING256')),('TECHNICAL_PARAMETER_VALUE',('N_TECH_PARAM','STRING256'))):
        var=ds.createVariable(n,'S1',dims,fill_value=' ')
        var.long_name='Name of technical parameter' if n.endswith('NAME') else 'Value of technical parameter'
    cyc=ds.createVariable('CYCLE_NUMBER','i4',('N_TECH_PARAM',),fill_value=np.int32(99999))
    cyc.long_name='Float cycle number'
    cyc.conventions='0...N, 0 : launch cycle (if exists), 1 : first complete cycle'
    inst = DAC_INSTITUTION.get(centre, centre) if centre else ""
    ds.setncatts({'title':'Argo float auxiliary technical data file','institution':inst,'source':'Argo float','references':'http://www.argodatamgt.org/Documentation','user_manual_version':'1.0','Conventions':'CF-1.6 Coriolis-Argo-Aux-1.0','decoder_version':'argo-decoder-python (partial technical controls)'})
    return ds


def write_vitals_controls(directory,wmo,records,blocked_events,*,data_centre='IN',allow_partial=False,overwrite=False):
    """Write only supported channels; default refuses an incomplete bundle.

    Explicit partial mode preserves EVERY unresolved value/event in the required
    receipt. No standard production driver is switched to partial mode implicitly.
    Source sequence is retained, including equal timestamps and companion files.
    """
    directory=Path(directory)
    blocked=list(blocked_events)
    for r in records:
        r.juld  # validate every source clock before any output file is created
        channels=CHANNELS if r.kind=='VITALS_CORE' else (WATCHDOG,) if r.kind=='WD_CNT' else None
        if channels is None or len(r.values)!=len(channels):raise ValueError('Unknown record kind or payload width')
        for value,(lookup,name,unit,route) in zip(r.values,channels):
            if not np.isfinite(value):raise ValueError('Non-finite source values require explicit missing-value policy')
            if route!='BLOCKED' and float(np.float32(value))!=value:raise ValueError('Source value is not exactly representable as required NC_FLOAT; native evidence required')
            if route!='BLOCKED' and value==99999.:raise ValueError('Source value collides with published fill sentinel')
            if route=='BLOCKED':blocked.append({'occurrence':r.receipt(),'lookup':lookup,'value':value,'reason':'unit conflict: vendor manual mAh, binary label AHrs, Coriolis attribute mA/hour; no conversion or unit assertion'})
    if blocked and not allow_partial:raise IncompleteTechnicalMapping(blocked)
    products=[];links=[]
    directory.mkdir(parents=True,exist_ok=True)
    paths=[directory/f'{wmo}_tech.nc',directory/f'{wmo}_tech_aux.nc',directory/f'{wmo}_technical_receipt.json.gz']
    if not overwrite and any(p.exists() for p in paths):raise FileExistsError('Refusing to overwrite existing technical evidence')
    if overwrite:
        for p in paths:
            if p.exists():p.unlink()
    for route,path in zip(('TECH','AUX'),paths):
        rows=[]
        for r in records:
            channels=CHANNELS if r.kind=='VITALS_CORE' else (WATCHDOG,)
            selected=[(c,v) for c,v in zip(channels,r.values) if c[3]==route]
            if selected:rows.append((r,selected))
        if not rows:continue
        ds=_dataset(wmo,route,data_centre)
        try:
            ds.createDimension('N_TECH_MEASUREMENT',len(rows))
            v=ds.createVariable('JULD','f8',('N_TECH_MEASUREMENT',),fill_value=999999.)
            v.setncatts({'long_name':'Julian day (UTC) of each measurement','standard_name':'time','units':'days since 1950-01-01 00:00:00 UTC','conventions':'Relative julian days with decimal part (as parts of day)','axis':'T'})
            cy=ds.createVariable('CYCLE_NUMBER_MEAS','i4',('N_TECH_MEASUREMENT',),fill_value=99999)
            mc=ds.createVariable('MEASUREMENT_CODE','i4',('N_TECH_MEASUREMENT',),fill_value=99999)
            mc.setncatts({'long_name':'Flag referring to a measurement event in the cycle','conventions':'Argo reference table 15'})
            status=None;qc_vars={}
            if route=='AUX':
                v.long_name='Julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME'
                cy.long_name='Float cycle number of the measurement'
                cy.conventions='0...N, 0 : launch cycle, 1 : first complete cycle'
                adj=ds.createVariable('JULD_ADJUSTED','f8',('N_TECH_MEASUREMENT',),fill_value=999999.)
                adj.setncatts({a:v.getncattr(a) for a in v.ncattrs() if a!='_FillValue'})
                adj.long_name='Adjusted julian day (UTC) of each measurement relative to REFERENCE_DATE_TIME'
                # Modified dates and QC remain fill; the float transmits one clock.
                for n,desc,table in [('JULD_STATUS','Status of the date and time',19),('JULD_QC','Quality on date and time',2),('JULD_ADJUSTED_STATUS','Status of the JULD_ADJUSTED date',19),('JULD_ADJUSTED_QC','Quality on adjusted date and time',2)]:
                    flag=ds.createVariable(n,'S1',('N_TECH_MEASUREMENT',),fill_value=' ')
                    flag.long_name=desc;flag.conventions=f'Argo reference table {table}'
                status=ds['JULD_STATUS']
                # Reference writer creates one QC variable per measurement parameter.
            params={c[1]:c for r,vals in rows for c,value in vals}
            if route=='AUX':
                ds.createDimension('N_TECH_MEAS_PARAM',len(params))
                names=ds.createVariable('TECHNICAL_MEASUREMENT_PARAMETERS','S1',('N_TECH_MEAS_PARAM','STRING256'),fill_value=' ')
                names.setncatts({'long_name':'List of available technical parameters for the station','conventions':'Reference table AUX_3b'})
                arr=np.full((len(params),256),b' ',dtype='S1')
                for i,name in enumerate(params):arr[i,:len(name)]=np.frombuffer(name.encode('ascii'),dtype='S1')
                names[:]=arr
            for name,(lookup,_,unit,_) in params.items():
                var=ds.createVariable(name,'f4',('N_TECH_MEASUREMENT',),fill_value=99999.)
                var.units=unit
                if name=='VOLTAGE_Battery':var.long_name='battery voltage when battery capacity is unknown'
                elif name=='PRESSURE_InternalVacuum':var.long_name='Internal vacuum pressure'
                elif name=='PRESSURE_AirBladder':var.long_name='Air bladder pressure'
                elif name=='FIRMWARE_WATCHDOG_COUNT':var.long_name='Number of registered watchdog events'
                if route=='AUX':
                    qc=ds.createVariable(name+'_QC','S1',('N_TECH_MEASUREMENT',),fill_value=' ')
                    qc.long_name='quality flag';qc.conventions='Argo reference table 2'
                    qc_vars[name]=qc
            for index,(r,vals) in enumerate(rows):
                v[index]=r.juld;cy[index]=r.cycle
                if status is not None:
                    status[index]='2'  # R19 2: value transmitted by the float
                for (lookup,name,unit,_),value in vals:
                    ds[name][index]=value
                    if name in qc_vars:
                        qc_vars[name][index]='0'  # table 2: no QC performed
                    links.append({'source':r.receipt(),'lookup':lookup,'parameter':name,'unit':unit,'value':value,'JULD':r.juld,'MC':None,'output':path.name,'record':index})
            ds.comment='Partial technical control; unresolved data retained in '+paths[2].name+'; not a complete deployable technical bundle; TECH_AUX_PARAM_LABEL catalog unavailable in recovered sources. Native NC_FLOAT values preserved exactly.'
            out=netCDF4.Dataset(str(path),'w',format=APF11_NC_FORMAT)
            try:
                for n,d in ds.dimensions.items():out.createDimension(n,None if d.isunlimited() else len(d))
                for n,x in ds.variables.items():
                    kw={'fill_value':x._FillValue} if '_FillValue' in x.ncattrs() else {}
                    y=out.createVariable(n,x.dtype,x.dimensions,**kw);y.setncatts({a:x.getncattr(a) for a in x.ncattrs() if a!='_FillValue'});y[:]=x[:]
                out.setncatts({a:ds.getncattr(a) for a in ds.ncattrs()})
            finally:out.close()
        finally:ds.close()
        products.append({'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt={'status':'PARTIAL_CONTROL' if blocked else 'SUPPORTED_VITALS_ONLY','mapping_commit':'d4069390b21fe1e144fde6c503c99dcf03371177','precision':'NC_FLOAT; exact native values; proved CSV companions retain original text and separate output occurrences','MC_policy':'fill; no source code or validated anchor association supplied','source_occurrences':len(records),'links':links,'blocked':blocked,'products':products}
    paths[2].write_bytes(gzip.compress(json.dumps(receipt,separators=(',',':')).encode(),mtime=0))
    return paths[2]
