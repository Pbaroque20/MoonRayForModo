
            // Re-converge all sampled lanes before collecting. Invalid lanes also
            // own tickets and must be retired; no native arena data is retained.
            uniform float xpu2Post[8*8];
            uniform int xpu2Mask=0;
            foreach_active (lane) {
                uniform int b=lane*8;
                xpu2Mask |= 1 << lane;
                xpu2Post[b]=extract(bsmp[s].wi.x,lane);
                xpu2Post[b+1]=extract(bsmp[s].wi.y,lane);
                xpu2Post[b+2]=extract(bsmp[s].wi.z,lane);
                xpu2Post[b+3]=extract(bsmp[s].f.r,lane);
                xpu2Post[b+4]=extract(bsmp[s].f.g,lane);
                xpu2Post[b+5]=extract(bsmp[s].f.b,lane);
                xpu2Post[b+6]=extract(bsmp[s].pdf,lane);
                xpu2Post[b+7]=0.f;
            }
            xpu2BatchedCollect(xpu2Post,xpu2Mask,slot);
            foreach_active (lane) {
                bsmp[s].f.r=insert(bsmp[s].f.r,lane,xpu2Post[lane*8+3]);
                bsmp[s].f.g=insert(bsmp[s].f.g,lane,xpu2Post[lane*8+4]);
                bsmp[s].f.b=insert(bsmp[s].f.b,lane,xpu2Post[lane*8+5]);
            }
            if (!valid[slot]) { continue; }
