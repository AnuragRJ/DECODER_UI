# ---------------------------------------------------------------------------
# Python 3 port of the vendor-supplied Teledyne Webb Research APF11 decoder.
#
# Source: APF-11-metadata-and-raw-files/apf11dec.py (v2.12.2.1), kept UNMODIFIED
# in ../source/. This port changes ONLY what is required to execute under
# Python 3, because the original is Python 2 and cannot run at all here:
#
#   * 9 x `print 'x'` statements  -> print('x')
#   * 6 x ord(byte) on bytes      -> the byte is already an int under py3
#
# Every record type, ID, struct format string and field-name tuple is
# byte-for-byte identical to the vendor original. The decoding logic is
# unchanged: same 1-byte length framing, same filename-based dispatch, same
# per-ID lookup table. Nothing was added, removed or reordered.
#
# The vendor original handles ONLY science_log and vitals_log (it dispatches
# on the filename). system_log / production_log / suna_log are already text and
# are handled by apf11_extract.py, which does not touch binary records.
# ---------------------------------------------------------------------------

'''
@organization: Teledyne Webb Resarch
@file: apf11dec.py

@version: 2.12.2.1
@note: Change Global when changing the version

@summary: convert an APF11 binary data file to .csv

Revision History:
@change: 12-Nov-2012 dpingal@teledyne.com Initial
@change: 16-Nov-2012 dpingal@teledyne.com Added 'z' format for null terminated strings
@change: 24-Jan-2013 dpingal@teledyne.com Catches exception, prints out info about bad input.  Added debug option.
@change: 25-Feb-2013 dpingal@teledyne.com Fixed timestamp date format
@change: 27-Dec-2014 lbovie@teledyne.com Added RBR log items PTSC & PTSC_BINDATA
@change: 13-Feb-2016 Brian.Leslie@teledyne.com Updated record ids
@change: 13-Feb-2016 Brian.leslie@teledyne.com Fixed MANTIS 3482
@change: 06-Sep-2018 Brian.Leslie@teledyne.com Removed Seascan support and added RBR LGR

@todo: verify data decimal precision matches decoder output
'''

import os
import struct
import time

debug = False
__version__="2.12.2.1"

def dump(bin):
    result = ''
    for byte in bin:
        result += '%02x ' % (byte if isinstance(byte, int) else ord(byte))
    return result[:-1]

def unpack_with_final_asciiz(fmt, dat):
    """
    Unpack binary data, handling a null-terminated string at the end
    (and only at the end) automatically.

    The first argument, fmt, is a struct.unpack() format string with the
    following modfications:
    If fmt's last character is 'z', the returned string will drop the NUL.
    """
    # Just pass on if no special behavior is required
    if fmt[-1] != 'z':
        return struct.unpack(fmt, dat)

    # Use format string to get size of contained string and rest of record
    str_len = len(dat) - struct.calcsize(fmt[:-1])
    new_fmt = '%s%ds' % (fmt[:-1], str_len)
    return struct.unpack(new_fmt, dat)

# Convert Unix timestamp to a human readable string
def ts_str(ts):
    return time.strftime('%Y%m%dT%H%M%S', time.gmtime(ts))

# Note that format specifier appears to round, not truncate
def f0_str(val):
    return '%0.0f' % val

def f1_str(val):
    return '%0.1f' % val

def f2_str(val):
     return '%0.2f' % val

def f3_str(val):
     return '%0.3f' % val

def f4_str(val):
     return '%0.4f' % val

def f5_str(val):
     return '%0.5f' % val
 
def f6_str(val):
     return '%0.6f' % val

# Instances of this class represent a single record type
class datarecord(object):
    # Dictionaries of custom formatters:
    # formats = what's the underlying type (must be valid for struct.unpack)
    # processors = functions to call after converting
    # e.g. timestamp is a long int, gets converted to string by ts_str
    # also, we can handle a trailing null-terminated string
    formats = { 'T': 'I', '0':'f', '1':'f', '2':'f', '3':'f', '4':'f', '5':'f', '6':'f'}
    posts = { 'T': ts_str, '0': f0_str, '1':f1_str, '2':f2_str, '3':f3_str, '4':f4_str, '5':f5_str, '6':f6_str, 'f':f5_str }

    # Create a record type:
    # id = binary record ID in file
    # name = record name
    # fmt = a format string to convert type (see struct module doco)
    # fields = names of output fields
    def __init__(self, id, name, fmt, fields):
        self.id = id
        self.fmt = '<' + ''.join([ datarecord.formats.get(c) or c for c in fmt ])
        self.post = tuple([ datarecord.posts.get(c) for c in fmt ])
        self.name = name
        self.fields = fields

    # decode a binary record
    def decode(self, record):
        id = struct.unpack('<BB', record[0:2])[0]
        if self.id != id:
            print('decode: expected ID %d, got %d' % (self.id, id))
            return None
        data = unpack_with_final_asciiz(self.fmt, record[1:])
        result = []
        for n, value in enumerate(data):
            if self.post[n]:
                result.append(self.post[n](value))
            else:
                result.append(value)
        return result

# Instances of this class lookup the record type and deal with it appropriately
class decoder(object):
    # Empty to start
    def __init__(self):
        self.types = {}

    def __getitem__(self, id):
        return self.types[id].name

    # Add type definition to our list
    def addtype(self, id, name, fmt, names):
        self.types[id] = datarecord(id, name, fmt, names)

    # Decode anything: get ID field from record and look it up self.types
    # use that decoder to interpret the record
    def decode(self, data):
        type_n = data[0] if isinstance(data[0], int) else ord(data[0])
        type = self.types[type_n]
        return [type.name] + type.decode(data)

'''
Vitals Log Decoder
'''
# Make the decoders
vitals = decoder()

# LOG_VITALS_MESSAGE
vitals.addtype(0, 'Message', 'Tz', ('timestamp', 'message'))

# ----- Core Vital Logs -----

#   LOG_VITALS_CORE
vitals.addtype(1, 'VITALS_CORE', 'T3H3H333H33h', ('timestamp', 'air_bladder(dbar)', 'air_bladder(cnts)',
                                   'battery_voltage(V)', 'battery_voltage(cnts)',
                                   'humidity', 'leak_detect(V)',
                                   'vacuum(dbar)', 'vacuum(cnts)',
                                   'coulomb(AHrs)', 'battery_current(mA)',
                                   'battery_current_raw'))

# LOG_VITALS_IRIDIUM_CSQ
vitals.addtype(2, 'RSSI', 'TB', ('timestamp', 'RSSI'))

#LOG_VITALS_WATCHDOG_CNT
vitals.addtype(3, 'WD_CNT', 'Ti',  ('Timestamp', 'Events(count)'))


# ----- Feature Vital Logs -----

# LOG_VITALS_ICE_DETECT
vitals.addtype(50, 'ICE_DETECT', 'Ti34i',('timestamp', 'mission','medianP', 'medianT', 'samples'))

# LOG_VITALS_ICE_CAP
vitals.addtype(51, 'ICE_CAP', 'Ti34i', ('timestamp', 'mission','medianP', 'medianT', 'samples'))

# LOG_VITALS_ICE_BREAKUP
vitals.addtype(52, 'ICE_BREAKUP', 'Ti34i', ('timestamp', 'mission','medianP', 'medianT', 'samples'))


# ----- Experimental Vital Logs -----

# LOG_VITALS_BUOY,
vitals.addtype(225, 'BuoyancyAdjust', 'Tiii33322i', ('Timestamp', 'Travel(counts)','Final(counts)','Duration(sec)', 'Coul(mA-hr)','I_avg(A)','I_max(A)','Battery(V)','Battery_min(V)', 'Updates(count)'))

# LOG_VITALS_AIR,
vitals.addtype(227, 'AirInflate', 'T0033322i', ('Timestamp', 'Pulses(count)','Duration(sec)', 'Coul(mA-hr)','I_avg(A)','I_max(A)','Battery(V)','Battery_min(V)', 'Updates(count)'))

# LOG_VITALS_MODEM,
vitals.addtype(229, 'Modem', 'T0033322i', ('Timestamp', 'Data(bytes)','Duration(sec)', 'Coul(mA-hr)','I_avg(A)','I_max(A)','Battery(V)','Battery_min(V)', 'Updates(count)'))

# LOG_VITALS_CTD
vitals.addtype(230, 'VITALS_CTD', 'T3H33H', ('timestamp', 'battery_voltage(V)','battery_voltage(cnts)', 'battery_current(mA)', 'ctd_current(mA)', 'ctd_current(cnts)'))

'''
Science Log Decoder
'''
science = decoder()


# ----- Core Science Logs -----

# LOG_SCIENCE_MESSAGE
science.addtype(0, 'Message', 'Tz', ('timestamp', 'message'))

# LOG_SCIENCE_GPS
science.addtype(1, 'GPS', 'T66i', ('timestamp', 'latitude', 'longitude','nsat'))


# ----- SBE CTD Sensor Science Logs -----
 
# LOG_SCIENCE_CTD_CP_BINDATA
science.addtype(10, 'CTD_bins', 'TIH3', ('timestamp', 'samples', 'bins', 'maxpress'))

# LOG_SCIENCE_CTD_P
science.addtype(11, 'CTD_P', 'T2', ('timestamp', 'pressure'))

# LOG_SCIENCE_CTD_PT
science.addtype(12, 'CTD_PT', 'T24', ('timestamp', 'pressure', 'temperature'))

# LOG_SCIENCE_CTD_PTS
science.addtype(13, 'CTD_PTS', 'T244', ('timestamp', 'pressure', 'temperature', 'salinity'))

# LOG_SCIENCE_CTD_CP_PTS
science.addtype(14, 'CTD_CP', 'T244h', ('timestamp', 'pressure', 'temperature', 'salinity', 'samples'))

# LOG_SCIENCE_CTD_PTSH
science.addtype(15, 'CTD_PTSH', 'T2446', ('timestamp', 'pressure', 'temperature', 'salinity', 'ph'))

# LOG_SCIENCE_CTD_CP_PTSH
science.addtype(16, 'CTD_CP_H', 'T244h6h', ('timestamp', 'pressure', 'temperature', 'salinity', 'samples', 'ph', 'samples'))


# ----- RBR LGR Sensors Science Logs -----

# LOG_SCIENCE_RBR_LGR_PTSCI
science.addtype(20, 'LGR_PTSCI', 'Tfffff', ('timestamp','pressure','temperature', 'salinity', 'conductivity', 'internal_temperature'))

# LOG_SCIENCE_RBR_LGR_CP_PTSCI
science.addtype(21, 'LGR_CP_PTSCI', 'Tfffffh',  ('timestamp', 'pressure', 'temperature', 'salinity', 'conductivity', 'internal_temperature', 'samples'))

# LOG_SCIENCE_RBR_LGR_CP_PT
science.addtype(22, 'LGR_CP_PT', 'Tffh',  ('timestamp', 'pressure', 'temperature', 'samples'))

# LOG_SCIENCE_RBR_LGR_P
science.addtype(23, 'LGR_P', 'Tf', ('timestamp', 'pressure'))

# LOG_SCIENCE_RBR_LGR_PT
science.addtype(24, 'LGR_PT', 'Tff', ('timestamp', 'pressure', 'temperature'))

# LOG_SCIENCE_RBR_LGR_PTS
science.addtype(25, 'LGR_PTS', 'Tfff', ('timestamp', 'pressure', 'temperature', 'salinity'))

# LOG_SCIENCE_RBR_LGR_PTSC
science.addtype(26, 'LGR_PTSC', 'Tffff', ('timestamp', 'pressure', 'temperature', 'salinity', 'conductivity'))


# ----- Optode Sensor Science Logs -----

# LOG_SCIENCE_OPTODE
science.addtype(40, 'O2', 'Tffffffffff', ('timestamp', 'O2', 'AirSat', 'Temp', 'CalPhase', 'TCPhase', 'C1RPh', 'C2RPh', 'C1Amp', 'C2Amp', 'RawTemp'))


# ----- FLBB Sensor Science Logs -----

# LOG_SCIENCE_FLBB
science.addtype(50, 'FLBB', 'Thhhhh', ('timestamp', 'chl_wave', 'chl_sig', 'bsc_wave', 'bsc_sig', 'therm_sig'))

# LOG_SCIENCE_FLBB_BB
science.addtype(51, 'FLBB_BB', 'Thhhhhhh', ('timestamp', 'chl_wave', 'chl_sig', 'bsc_wave0', 'bsc_sig0', 'bsc_wave1' 'bsc_sig1','therm_sig'))

# LOG_SCIENCE_FLBB_CD
science.addtype(52, 'FLBB_CD', 'Thhhhhhh', ('timestamp', 'chl_wave', 'chl_sig', 'bsc_wave', 'bcs_sig', 'cd_wave', 'cd_sig', 'therm_sig'))

# LOG_SCIENCE_FLBB_FL3
science.addtype(53, 'FLBB_FL3', 'Thhhhhhh', ('timestamp', 'bsc_wave', 'bcs_sig', 'chl_wave', 'chl_sig', 'cd_wave', 'cd_sig', 'therm_sig'))


# ----- Radiance Sensor Science Logs -----

 # LOG_SCIENCE_RAD
science.addtype(60, '504R', 'Tffff', ('timestamp', 'channel1',  'channel2',  'channel3',  'channel4'))

# LOG_SCIENCE_IRAD
science.addtype(61, '504I', 'Tffff', ('timestamp', 'channel1',  'channel2',  'channel3', 'channel4'))


# ----- Crover Sensor Science Logs -----

# LOG_SCIENCE_CROVER
science.addtype(70, 'CROVER', 'Thhhhf', ('timestamp', 'reference', 'raw_sig', 'corr_sig', 'therm', 'attenuation(m^-1)'))

# ----- Attitude/Compass Sensor Science Logs -----

# LOG_SCIENCE_COMPASS
science.addtype(80, 'Compass', 'Tffff', ('timestamp', 'heading', 'pitch', 'roll', 'dip'))


# ----- JFE Advantech's RINKO-FT sensor Science Logs -----

# LOG_SCIENCE_RINKO_FT
science.addtype(90, 'O2', 'THHHHHHI', ('timestamp', 'temperature', 'dissolved_oxygen', 'blue_phase', 'red_phase', 'blue_amplitude', 'red_amplitude', 'accumulated_led_time'))

# ----- Satlantic SUNA (Deep) Sensor Science Logs -----

# LOG_SCIENCE_SUNA

science.addtype(100, 'NO3', 'T2', ('timestamp', 'nitrate'))

EXPERIMENTAL = range(225,255)
EXCLUDE_EXPERIMENTAL=False
# Convert a .bin file to .csv
def decode(fn):
    ifile = open(fn, 'rb')
    ofile = open(os.path.splitext(fn)[0] + '.csv', 'w')

    while True:
        len_chr = ifile.read(1)
        if len(len_chr) < 1:
            break
        
        rec_len = len_chr[0] if isinstance(len_chr, bytes) else ord(len_chr)
        rec = ifile.read(rec_len)
        record_id = rec[0] if isinstance(rec[0], int) else ord(rec[0])
        if record_id in EXPERIMENTAL:
            if EXCLUDE_EXPERIMENTAL:
                continue
         
        try:
            # handle decoding based on file name
            if fn.find("science_log") >= 0:
                ofile.write(','.join([str(x) for x in science.decode(rec)]) + '\n')
                if debug:
                    print('at', ifile.tell(), 'len', rec_len, 'record_id', record_id, science[record_id])
    
            elif fn.find("vitals_log") >= 0:
                ofile.write(','.join([str(x) for x in vitals.decode(rec)]) + '\n')
                if debug:
                    print('at', ifile.tell(), 'len', rec_len, 'record_id', record_id, vitals[record_id])
    
            if debug:
                print(dump(rec[1:]))
                
        except:
            if fn.find("science_log") >= 0:
                print('ERROR at', ifile.tell(), 'len', rec_len, 'record_id', record_id, science[record_id])
            elif fn.find("vitals_log") >= 0:
                print('ERROR at', ifile.tell(), 'len', rec_len, 'record_id', record_id, vitals[record_id])
            print('- can\'t interpret:', dump(rec[1:]))

        if debug:  
            print('---------------------------------------------------')

# Top level: convert all files listed in argv to .csvs
if __name__ == '__main__':
    import sys, getopt
    try:
        (opts, files) = getopt.getopt(sys.argv[1:], 'd', 'debug')
        for opt, a in opts:
            if opt == '-d' or opt == '--debug':
                debug = True
    except:
        print('Usage:  apf11dec [-d, --debug] files')
        sys.exit(-1)
    if len(files) == 0:
        print('Usage:  apf11dec [-d, --debug] files')
    for fn in files:
        decode(fn)
