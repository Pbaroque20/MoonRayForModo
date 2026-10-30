"""Gates for live fused shader/contribution images and deliberate rejection."""
from xpu2.film_evidence import validate_profile


def validate_fused(p,mode):
    keys=('fused_calls','shader_checked','shader_unsupported','shader_mismatch')
    if any(type(p.get(k)) is not int or p[k]<0 for k in keys):raise ValueError('Missing fused shader evidence')
    if not p['fused_calls'] or p['fused_calls']!=p['calls']:raise ValueError('Fusion not exercised')
    if mode=='bad_shader':
        if not p['shader_mismatch'] or p['shader_mismatch']!=p['eligible'] or p['mismatch']!=p['shader_mismatch']:raise ValueError('Shader guard did not reject all corrupted references')
        if any(p[k] for k in ('accepted','replaced','cpu_skipped','shader_checked','errors','cleanup_errors')):raise ValueError('Rejected shader contaminated output or failed cleanup')
        return dict(status='passed',mode=mode,rejected=p['shader_mismatch'])
    result=validate_profile(p,mode)
    if p['shader_mismatch']:raise ValueError('Fused shader mismatch')
    if p['shader_checked']!=p['accepted']:raise ValueError('Contribution accepted without shader verification')
    return result


def compare_fused(separate,fused):
    validate_profile(separate,'fast');validate_fused(fused,'fast')
    if separate.get('fused_calls')!=0:raise ValueError('Separate control used fusion')
    for k in ('eligible','accepted','cpu_skipped','packets'):
        if separate[k]!=fused[k]:raise ValueError('Completed contribution work changed: '+k)
    return dict(status='passed',accepted=fused['accepted'],fused_dispatches=fused['dispatches'],separate_contribution_dispatches=separate['dispatches'])
