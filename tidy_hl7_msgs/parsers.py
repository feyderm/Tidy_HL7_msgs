'''
Parsers
'''

import re
import itertools
import numpy as np
import pandas as pd
from tidy_hl7_msgs.helpers import concat, flatten

def parse_msgs(loc_txt, msgs):
    ''' Parse messages at a given location

    Parameters
    ----------
    loc_txt : string of location to parse
    msgs : list(string)

    Returns
    -------
    List(list(string))

    Examples
    --------
    >>> msg1 = '...AL1|3|DA|1545^MORPHINE^99HIC|||20080828|||...'
    >>> msg2 = '...AL1|1|DRUG|00000741^OXYCODONE||HYPOTENSION...'
    >>> parse_msgs("AL1.3.1", [msg1, msg2])
    >>> [['1545'], ['00000741']]
    >>>
    >>> # multiple segments per message
    >>> seg_1 = '...AL1|1|DRUG|00000741^OXYCODONE||HYPOTENSION'
    >>> seg_2 = 'AL1|2|DRUG|00001433^TRAMADOL||SEIZURES~VOMITING...'
    >>> msg3 = seg_1 + seg_2
    >>> parse_msgs("AL1.3.1", [msg1, msg3])
    >>> [['1545'], ['00000741', '00001433']]
    '''
    loc = parse_loc_txt(loc_txt)
    parser = get_parser(loc)
    return list(map(parser, msgs))

def parse_loc_txt(loc_txt):
    ''' Parse HL7 message location

    Parameters
    ----------
    loc_txt : string of location

    Returns
    -------
    Dictionary of location attributes and parsed elements

    Raises
    ------
    ValueError if location syntax is incorrect

    Examples
    --------
    >>> parse_loc_txt('PR1.3')
    {'seg': 'PR1', 'field': 3, 'depth': 2}
    >>>
    >>> parse_loc_txt('DG1.3.1')
    {'seg': 'DG1', 'field': 3, 'comp': 0, 'depth': 3}

    '''
    loc = {}
    loc_split = loc_txt.split(".")
    loc['depth'] = len(loc_split)

    if loc['depth'] not in [2, 3]:
        raise ValueError(
            "Syntax of location must be either <segment>.<field> or "
            "<segment>.<field>.<component>"
        )

    loc['seg'] = loc_split[0]
    loc['field'] = int(loc_split[1])

    if loc['seg'] == "MSH":
        loc['field'] -= 1

    if loc['depth'] == 3:
        loc['comp'] = int(loc_split[2]) - 1

    return loc

def get_parser(loc):
    ''' Higher-order function to parse a location from an HL7 message

    Parameters
    ----------
    loc : dict of location attributes and values

    Returns
    -------
    Function to parse an HL7 message at a given location

    Examples
    --------
    >>> msg = '...AL1|3|DA|1545^MORPHINE^99HIC|||20080828|||...'
    >>> parse_allergy_type = get_parser("AL1.2")
    >>> parse_allergy_type(msg)
    >>> ['DA']
    >>>
    >>> parse_allergy_code_text = get_parser("AL1.3.2")
    >>> parse_allergy_code_text(msg)
    >>> ['MORPHINE']
    >>>
    >>> seg_1 = '...AL1|3|DA|1545^MORPHINE^99HIC|||20080828|||'
    >>> seg_2 = 'AL1|4|DA|1550^CODEINE^99HIC|||20101027|||...'
    >>> msg_2 = seg_1 + seg_2
    >>> parse_allergy_code_text(msg_2)
    >>> ['MORPHINE', 'CODEINE']
    '''
    def parser(msg):
        ''' Parse an HL7 message

        Parameters
        ----------
        msg : string

        Returns
        -------
        List(string)
        '''
        # pylint: disable=expression-not-assigned
        field_sep, comp_sep = list(msg)[3:5]

        seg_re = loc['seg'] + re.escape(field_sep) + '.*(?=\\n)'
        segs = re.findall(seg_re, msg)

        if not segs:
            data = ['no_seg']
        else:
            data = []
            for seg in segs:
                seg_split = seg.split(field_sep)
                if loc['depth'] == 2:
                    try:
                        field_val = seg_split[loc['field']]
                    except IndexError:
                        field_val = np.nan
                    # if sep present for split but no data (i.e empty string)
                    data.append(field_val) if field_val else data.append(np.nan)
                else:
                    assert loc['depth'] == 3
                    try:
                        field_val = seg_split[loc['field']]
                        comp_val = field_val.split(comp_sep)[loc['comp']]
                    except IndexError:
                        comp_val = np.nan
                    # if sep present for split but no data (i.e empty string)
                    data.append(comp_val) if comp_val else data.append(np.nan)
        return data
    return parser

def parse_msg_id(id_locs_txt, msgs):
    ''' Parse message IDs from raw HL7 messages

    The message identifier is a concatination of the each ID location value,
    which must not be missing and which must be a single value for each
    location (i.e. the location must be for a segment found only once in a
    message). Returns a single string per message. Its value must be unique
    for each message because it is used when joining data elements within a
    message.

    Parameters
    ----------
    id_locs_txt : list(string)
    msgs : list(string)

    Returns
    -------
    List(string)

    Raises
    ------
    RuntimeError if a location is missing a segment
    RuntimeError if a location value is NA
    RuntimeError if a location has multiple values
    RuntimeError if message IDs are not unique

    Examples
    --------
    >>> parse_msg_id(['MSH.7', 'PID.3.1', 'PID.3.4'], msgs)
    ['Facility1,68188,1719801063', 'Facility2,588229,1721309017']
    '''
    ids_per_seg = list(map(parse_msgs, id_locs_txt, itertools.repeat(msgs)))
    ids_per_msg = [np.array(flatten(msg_ids), dtype=object) for msg_ids in ids_per_seg]

    # id segment is missing
    loc_missing_seg = ['no_seg' in list(id_val) for id_val in ids_per_msg]
    if any(loc_missing_seg):
        raise RuntimeError(
            "Segment missing for message ID location: {locs}".format(
                locs=", ".join(itertools.compress(id_locs_txt, loc_missing_seg))
            )
        )

    # id values are NA
    loc_has_na = [any(pd.isnull(id_val)) for id_val in ids_per_msg]
    if any(loc_has_na):
        raise RuntimeError(
            "Message ID location missing value: {locs}".format(
                locs=", ".join(itertools.compress(id_locs_txt, loc_has_na))
            )
        )

    # id has multiple values
    loc_has_multi_val = (
        [any([len(id_val) > 1 for id_val in msg_ids]) for msg_ids in ids_per_seg]
    )
    if any(loc_has_multi_val):
        raise RuntimeError(
            "One or more message ID locations have multiple values: {locs}".format(
                locs=", ".join(itertools.compress(id_locs_txt, loc_has_multi_val))
            )
        )

    concatted = concat(ids_per_seg)

    if len(set(concatted)) != len(msgs):
        raise RuntimeError("Messages IDs are not unique")

    return concatted
