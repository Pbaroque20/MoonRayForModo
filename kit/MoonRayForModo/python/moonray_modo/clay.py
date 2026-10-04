"""Preview-only surface overrides; authored materials and displacement stay intact."""
CHOICES=(('Materials','materials'),('Clay — Terracotta','terracotta'),('Clay — Gray','gray'))
COLORS={'terracotta':[0.48,0.16,0.075],'gray':[0.35,0.35,0.35]}

def material(mode):
    color=COLORS.get(mode)
    if color is None:return None
    return {'color':list(color),'roughness':0.7,'metallic':0,'specular':[0.04,0.04,0.04]}
