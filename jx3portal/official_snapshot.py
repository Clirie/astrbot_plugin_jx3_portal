"""Read the official DOM at a readable width, then paginate at content boundaries."""
import asyncio
import io
import json
import zipfile
from PIL import Image, ImageOps
from .articles import official_url


def page_ranges(blocks, height, limit=1280):
    # Overlapping blocks (an image inside a paragraph, for example) are one unit.
    units = []
    for block in sorted(blocks, key=lambda b: (b['top'], b['bottom'])):
        if block['bottom'] <= block['top']: continue
        if units and block['top'] < units[-1]['bottom'] - .5:
            units[-1]['bottom'] = max(units[-1]['bottom'], block['bottom'])
            units[-1]['heading'] = units[-1]['heading'] or block.get('heading', False)
        else: units.append(dict(block))
    # A heading stays with the next block instead of becoming a page footer.
    for index in range(len(units)-2, -1, -1):
        if units[index].get('heading'):
            units[index]['bottom'] = units[index+1]['bottom'];units.pop(index+1)
    cuts = [0.0]
    for index, unit in enumerate(units):
        if unit['bottom'] - cuts[-1] > limit and index:
            boundary = (units[index-1]['bottom'] + unit['top']) / 2
            if boundary - cuts[-1] >= min(320, limit*.3): cuts.append(boundary)
    if height > cuts[-1]: cuts.append(float(height))
    return list(zip(cuts, cuts[1:]))


def package_pages(images, layout):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for index, raw in enumerate(images):
            with Image.open(io.BytesIO(raw)) as source:
                frame = ImageOps.expand(source.convert('RGB'), border=(0, 28, 0, 28), fill='white')
                buffer = io.BytesIO();frame.save(buffer, 'JPEG', quality=90, optimize=True)
                archive.writestr(f'{index+1:03d}.jpg', buffer.getvalue())
        archive.writestr('layout.json', json.dumps(layout, ensure_ascii=False))
    return output.getvalue()


async def capture_official(page, url):
    if not official_url(url): raise ValueError('Unsupported official article URL')
    await page.goto(url, wait_until='domcontentloaded', timeout=20000)
    if not official_url(page.url): raise ValueError('Unexpected article redirect')
    article = page.locator('[class*="index-mainContainer-"]').first
    await article.wait_for(state='visible', timeout=12000)
    await page.wait_for_function("() => document.querySelector('[class*=\"index-mainContainer-\"]')?.innerText.length > 100", timeout=12000)
    await article.evaluate("""root => {
        root.id = 'portal-readable-article';
        let current = root;
        while (current.parentElement && current.parentElement !== document.body) {
            for (const sibling of current.parentElement.children) if (sibling !== current) sibling.style.setProperty('display','none','important');
            current = current.parentElement;
            for (const [key,value] of Object.entries({width:'auto',minWidth:'0',maxWidth:'none',margin:'0',padding:'0',transform:'none',position:'static',height:'auto'})) current.style[key] = value;
        }
        for (const sibling of document.body.children) if (sibling !== current) sibling.style.setProperty('display','none','important');
        document.body.style.cssText = 'margin:0;background:white;min-width:0;width:720px;';
        const style = document.createElement('style');style.textContent = `
        #portal-readable-article {box-sizing:border-box!important;width:720px!important;min-width:0!important;max-width:720px!important;height:auto!important;margin:0!important;padding:28px 36px!important;position:relative!important;left:0!important;top:0!important;transform:none!important;background:white!important;font-size:28px!important;line-height:1.65!important;overflow:visible!important;}
        #portal-readable-article [class*="index-articleContent-"], #portal-readable-article [class*="index-header-"] {width:auto!important;height:auto!important;font-size:28px!important;line-height:1.65!important;padding:0!important;}
        #portal-readable-article p, #portal-readable-article li, #portal-readable-article td, #portal-readable-article th, #portal-readable-article span, #portal-readable-article font, #portal-readable-article a {font-size:inherit!important;line-height:inherit!important;max-width:100%!important;}
        #portal-readable-article p {margin:0 0 20px!important;text-wrap:pretty;}
        #portal-readable-article h1, #portal-readable-article h2, #portal-readable-article h3, #portal-readable-article [class*="index-articleTitle-"] {font-size:34px!important;line-height:1.4!important;width:auto!important;max-width:100%!important;margin:24px 0 16px!important;}
        #portal-readable-article img, #portal-readable-article video, #portal-readable-article iframe {max-width:100%!important;height:auto!important;object-fit:contain;}
        #portal-readable-article table {width:100%!important;table-layout:fixed;word-break:break-word;}
        #portal-readable-article [class*="index-articleDate-"] {font-size:22px!important;}
        `;document.head.appendChild(style);
        for (const p of root.querySelectorAll('p')) if (!p.textContent.trim() && !p.querySelector('img,video,iframe,svg,canvas')) p.remove();
        for (const nav of root.querySelectorAll('[class*="index-positin_info-"]')) nav.style.display='none';
        const title = root.querySelector('[class*="index-articleTitle-"]');
        if (title) {title.style.setProperty('font-size','34px','important');title.style.setProperty('font-weight','700','important');title.style.setProperty('line-height','1.4','important');title.style.setProperty('white-space','normal','important');title.style.setProperty('height','auto','important');title.style.setProperty('text-align','left','important');title.style.setProperty('margin-bottom','18px','important');}
        for (const im of root.querySelectorAll('img')) {im.loading='eager';const src=im.dataset.src||im.dataset.original;if(src)im.src=src;}
        for (const video of root.querySelectorAll('video')) {video.muted=true;video.pause();}
    }""")
    await article.evaluate("""async root => {
        await Promise.race([Promise.all([...root.querySelectorAll('img')].map(im=>im.decode().catch(()=>{}))),new Promise(r=>setTimeout(r,12000))]);
        await document.fonts.ready;
        await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    }""")
    layout = await article.evaluate("""root => {
        const rect=root.getBoundingClientRect();
        const blocks=[...root.querySelectorAll('[class*="index-header-"],p,h1,h2,h3,h4,li,table,figure,img,video,iframe')].map(el=>{
            const r=el.getBoundingClientRect();return {top:r.top-rect.top,bottom:r.bottom-rect.top,heading:/^H[1-4]$/.test(el.tagName),tag:el.tagName};
        }).filter(b=>b.bottom>b.top);
        return {x:rect.x+scrollX,y:rect.y+scrollY,width:rect.width,height:rect.height,blocks,font:getComputedStyle(root.querySelector('p')||root).fontSize};
    }""")
    ranges = page_ranges(layout['blocks'], layout['height'])
    layout['pages'] = ranges
    images = []
    for top, bottom in ranges:
        images.append(await page.screenshot(type='jpeg', quality=94, full_page=True, animations='disabled', clip={'x':layout['x'],'y':layout['y']+top,'width':layout['width'],'height':bottom-top}, timeout=15000))
    return await asyncio.to_thread(package_pages, images, layout)
