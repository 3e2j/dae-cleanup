# Switch Toolbox .dae cleanup for Blender
An all-in-one [blender](https://www.blender.org/) model cleanup utility for .dae files exported from [Switch Toolbox](https://github.com/KillzXGaming/Switch-Toolbox). 

## Features
- Scale converter (scales the whole model from meter units to centimeters)
- Added support for mirroring textures by reformatting/condensing all "wrapping" variants into one image
- Force export .glb with original wrapping present in .dae file

## Why?
Switch Toolbox's .bmd to .dae export is 1:1, this results in models being far larger than they should be due to incorrect units being imported.

Blender also does not natively support wrapping parameters. This addon attempts to work around this limitation through two methods:
- Modifying the .glb export to manually include the wrapping parameters from the original .dae file
- Compressing the wrapping parameters onto the textures themselves, putting the required texture variants onto the same image file, essentially removing the need for wrapping parameters

### Things to know
- As a general guideline, the Blender scene should be empty before importing the .dae file
- Custom .glb export should only be used if the textures have not been condensed (reformatted)
- Some engines like Godot do not natively support wrapping parameters in .glb files. In this case, reformatting the textures and running a normal .glb export should fix these issues.
- Compressing/Reformatting the textures assumes that a wrapping mode of "REPEAT" is being used. The texture does not extend to encompass all of the mesh UVs, and instead still relies on the whole texture being repeated.

The add-on can be installed via Edit > Preferences > Add-ons > Install  
The add-on can be found on the Object View sidebar, see below:

![https://i.imgur.com/EJQ6lNZ.png](https://i.imgur.com/G1zQorB.png)
