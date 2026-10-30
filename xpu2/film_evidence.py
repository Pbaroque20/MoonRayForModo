"""Strict gates for live contribution-to-film evidence."""

def validate_profile(profile,mode):
    required=('calls','eligible','accepted','replaced','cpu_skipped','unsupported','mismatch','errors','cleanup_errors','total_ns','initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns')
    if any(type(profile.get(k)) is not int or profile[k]<0 for k in required):raise ValueError('Incomplete contribution profile')
    if not profile['calls'] or not profile['eligible'] or profile['mismatch'] or profile['cleanup_errors']:raise ValueError('Invalid contribution work or cleanup')
    if mode=='missing':
        if not profile['errors'] or profile['accepted'] or profile['replaced'] or profile['cpu_skipped']:raise ValueError('Missing-PTX fallback was not complete')
    else:
        if profile['errors'] or profile['accepted']!=profile['eligible']:raise ValueError('GPU contribution was not accepted')
        if mode=='audit':
            if profile['replaced'] or profile['cpu_skipped']:raise ValueError('Audit changed native output')
        elif mode in ('fast','sentinel'):
            if profile['replaced']!=profile['accepted'] or profile['cpu_skipped']!=profile['accepted']:raise ValueError('GPU contribution did not replace CPU work')
        else:raise ValueError('Unknown validation mode')
    if sum(profile[k] for k in ('initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns'))>profile['total_ns']:raise ValueError('Overlapping contribution timings')
    return dict(status='passed',cpu_contribution_skipped=profile['cpu_skipped'],mode=mode)


def compare_windows(packet,window):
    """A lower launch count is evidence only if the same real work was completed."""
    for profile in (packet,window):
        validate_profile(profile,'fast')
        for key in ('packets','dispatches','max_slots'):
            if type(profile.get(key)) is not int or profile[key]<1:
                raise ValueError('Missing window dispatch evidence')
        if not 1<=profile['max_slots']<=16 or profile['dispatches']>profile['calls']:
            raise ValueError('Invalid window dispatch evidence')
        if profile['eligible']>profile['packets']*8 or profile['packets']>profile['calls']*profile['max_slots']:
            raise ValueError('Invalid packet accounting')
    if packet['max_slots']!=1 or window['max_slots']<=1:
        raise ValueError('Packet and window controls were not exercised')
    for key in ('packets','eligible','accepted','replaced','cpu_skipped','unsupported'):
        if packet[key]!=window[key]:raise ValueError('Contribution work changed: '+key)
    if window['dispatches']>=packet['dispatches']:
        raise ValueError('Dispatch count was not reduced')
    return dict(status='passed',packet_dispatches=packet['dispatches'],window_dispatches=window['dispatches'],
                dispatch_reduction=packet['dispatches']/window['dispatches'],
                packet_bridge_seconds=packet['total_ns']/1e9,window_bridge_seconds=window['total_ns']/1e9)
